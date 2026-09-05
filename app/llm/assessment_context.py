import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.database.models import Asset
from app.database.repository import (
    AssetStatusRepository,
    EvidenceObservationRepository,
    MarketRegimeRepository,
    MarketSnapshotRepository,
    NewsRepository,
)
from app.market_data.anomaly import detect_anomaly
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset


@dataclass
class AssetContext:
    asset: Asset
    screened: ScreenedAsset
    snapshot: object | None  # MarketSnapshot, left loosely typed to avoid an import cycle risk
    evidence_by_source: dict[str, dict] = field(default_factory=dict)
    news_summaries: list[str] = field(default_factory=list)
    status: str | None = None
    sanity_flagged: bool = False
    sanity_reason: str | None = None


@dataclass
class AssessmentContext:
    run_id: str
    as_of: datetime
    regime: MarketRegimeSnapshot | None
    assets: list[AssetContext]


def build_assessment_context(
    run_id: str,
    settings: Settings,
    candidates: list[ScreenedAsset],
    assets_by_id: dict[str, Asset],
    snapshot_repo: MarketSnapshotRepository,
    regime_repo: MarketRegimeRepository,
    evidence_repo: EvidenceObservationRepository,
    news_repo: NewsRepository,
    asset_status_repo: AssetStatusRepository,
) -> AssessmentContext:
    as_of = datetime.now(UTC)
    regime = regime_repo.get_latest()

    since = as_of - timedelta(hours=settings.news_lookback_hours)
    news_by_symbol = news_repo.get_recent_relevant_news(
        symbols=[c.symbol for c in candidates],
        since=since,
        until=as_of,
        limit_per_asset=settings.max_news_articles_per_asset,
    )

    asset_contexts = []
    for candidate in candidates:
        asset = assets_by_id.get(candidate.asset_id)
        if asset is None:
            continue

        snapshot = snapshot_repo.get_latest_snapshot(asset.id)
        sanity_flagged, sanity_reason = _run_sanity_check(asset.id, snapshot_repo)

        evidence_by_source: dict[str, dict] = {}
        for obs in evidence_repo.get_latest_by_asset(asset.id):
            evidence_by_source.setdefault(obs.source, obs.payload)

        status_entry = asset_status_repo.get_latest_status(asset.id)
        news_summaries = [
            f"[{a.published_at.isoformat()}] {a.title}: {a.summary or ''}"
            for a in news_by_symbol.get(candidate.symbol, [])
        ]

        asset_contexts.append(AssetContext(
            asset=asset,
            screened=candidate,
            snapshot=snapshot,
            evidence_by_source=evidence_by_source,
            news_summaries=news_summaries,
            status=status_entry.status if status_entry else None,
            sanity_flagged=sanity_flagged,
            sanity_reason=sanity_reason,
        ))

    return AssessmentContext(run_id=run_id, as_of=as_of, regime=regime, assets=asset_contexts)


def _run_sanity_check(asset_id: str, snapshot_repo: MarketSnapshotRepository) -> tuple[bool, str | None]:
    """Task 6: a simple outlier check on fresh market-data inputs against the
    same source's own recent readings, reusing 3b's anomaly-detection logic
    (app/market_data/anomaly.py) rather than a new implementation."""
    recent = snapshot_repo.get_recent_snapshots(asset_id, limit=10)
    if len(recent) < 3:
        return False, None

    ordered = list(reversed(recent))  # repo returns newest-first; detect_anomaly wants oldest-first
    closes = [float(s.price) for s in ordered]
    volumes = [float(s.volume_24h) for s in ordered if s.volume_24h is not None]
    if len(volumes) != len(closes):
        return False, None

    return detect_anomaly(closes, volumes)


SYSTEM_PROMPT_TEMPLATE = """\
You are a cryptocurrency market analyst providing a structured, independent \
CURRENT MARKET ASSESSMENT for a paper-trading research system — distinct \
from any prior research you may have produced. You will be given the shared \
market regime for this run, and per-asset market data, screening factors, \
derivatives/on-chain evidence, and news, all as of a fixed cutoff timestamp.

Every asset shares the SAME market regime this run — use exactly the \
`market_regime` value given, do not infer your own.

Respond with ONLY a single JSON object (no markdown fences, no commentary) \
matching exactly this shape, with one entry per asset provided:

{{
  "assessments": [
    {{
      "asset": "<symbol, must match input exactly>",
      "assessment_timestamp": "<ISO timestamp, use the 'As of' value given>",
      "horizon": {{"short_term_days": 7, "medium_term_days": 30, "long_term_days": 90}},
      "direction": {{"short_term": "BULLISH"|"NEUTRAL"|"BEARISH", "medium_term": ..., "long_term": ...}},
      "confidence": {{"short_term": <0.0-1.0>, "medium_term": <0.0-1.0>, "long_term": <0.0-1.0>}},
      "expected_return": {{"7d": <float>, "30d": <float>, "90d": <float>}},
      "risk": {{"score": <0.0-1.0>, "level": "LOW"|"MEDIUM"|"HIGH"}},
      "market_regime": "<the shared regime value given>",
      "key_drivers": [{{"factor": "...", "direction": "BULLISH"|"NEUTRAL"|"BEARISH", "importance": <0.0-1.0>, "reason": "..."}}],
      "key_risks": [{{"factor": "...", "direction": "BULLISH"|"NEUTRAL"|"BEARISH", "importance": <0.0-1.0>, "reason": "..."}}],
      "source_assessment": [{{"source": "<must be a source actually present in this asset's evidence>", "direction": "BULLISH"|"NEUTRAL"|"BEARISH", "importance": <0.0-1.0>, "reason": "..."}}],
      "thesis": "<concise overall thesis>",
      "invalidation_conditions": ["..."],
      "overall_assessment": "BULLISH"|"NEUTRAL"|"BEARISH"
    }}
  ]
}}

Only reference evidence sources actually present in an asset's context in \
`source_assessment` — never invent a source that wasn't given. If an \
asset's latest reading is flagged as a possible bad tick, treat it with \
appropriate caution rather than reasoning confidently from a number that \
may be a feed glitch. Base your analysis only on data given — do not \
reference events after the stated cutoff.

Prompt version: {prompt_version}\
"""


def render_prompt(context: AssessmentContext, prompt_version: str) -> tuple[str, str]:
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(prompt_version=prompt_version)

    lines = [f"As of: {context.as_of.isoformat()}"]
    if context.regime is not None:
        lines.append(f"Market regime (shared, use exactly this value): {context.regime.regime}")
        lines.append(f"Regime inputs: {context.regime.inputs}")
    lines.append("")

    for ac in context.assets:
        lines.append(f"## {ac.asset.symbol} ({ac.asset.name})")
        lines.append(f"Portfolio status: {ac.status or 'UNKNOWN'}")

        if ac.snapshot is not None:
            lines.append(
                f"Price: ${ac.snapshot.price} | Market cap: {ac.snapshot.market_cap} "
                f"| 24h volume: {ac.snapshot.volume_24h}"
            )
            lines.append(
                f"Change: 24h {ac.snapshot.price_change_24h}% | 7d {ac.snapshot.price_change_7d}% "
                f"| 30d {ac.snapshot.price_change_30d}%"
            )
        else:
            lines.append("No current market snapshot available.")

        if ac.sanity_flagged:
            lines.append(
                f"DATA QUALITY WARNING: latest reading flagged as a possible bad tick "
                f"({ac.sanity_reason}) — treat with appropriate caution."
            )

        lines.append(f"Composite factor score (3b, quantitative, non-narrative): {ac.screened.composite_factor_score}")
        if ac.screened.anomaly_flag:
            lines.append(f"Screening anomaly flag (3b): {ac.screened.anomaly_reason}")

        if ac.evidence_by_source:
            lines.append("Derivatives/on-chain evidence (3c):")
            for source, payload in ac.evidence_by_source.items():
                lines.append(f"  - {source}: {payload}")

        if ac.news_summaries:
            lines.append("Recent news:")
            for summary in ac.news_summaries:
                lines.append(f"  - {summary}")
        else:
            lines.append("Recent news: none found.")

        lines.append("")

    user_prompt = "\n".join(lines)
    return system_prompt, user_prompt


def compute_input_hash(system_prompt: str, user_prompt: str) -> str:
    return hashlib.sha256(f"{system_prompt}\n{user_prompt}".encode("utf-8")).hexdigest()
