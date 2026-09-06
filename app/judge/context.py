import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.database.evidence_provenance import group_observations_by_multi_entry_source
from app.database.models import Asset
from app.database.repository import (
    AdversarialResearchRepository,
    AssetStatusRepository,
    EvidenceObservationRepository,
    LLMAnalysisRepository,
    MarketRegimeRepository,
    ModelMarketAssessmentRepository,
    NewsRepository,
    PortfolioPositionRepository,
    SignalSourceRepository,
)
from app.llm.adversarial_schemas import AdversarialResearchRecord
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.llm.schemas import LLMAnalysisRecord
from app.market_data.schemas import MarketSnapshot
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset


@dataclass
class AssetJudgeContext:
    asset: Asset
    screened: ScreenedAsset
    snapshot: MarketSnapshot | None
    evidence_by_source: dict[str, dict] = field(default_factory=dict)
    # 3g fix: multi-entry per-asset sources (dated-futures term structure)
    # keep every distinct instrument, not one collapsed row — see
    # MULTI_ENTRY_ASSET_SOURCES in app/database/evidence_provenance.py.
    term_structure_by_source: dict[str, list[dict]] = field(default_factory=dict)
    assessments: list[ModelMarketAssessmentRecord] = field(default_factory=list)
    model_agreement: float = 1.0
    phase2_analyses: list[LLMAnalysisRecord] = field(default_factory=list)
    news_summaries: list[str] = field(default_factory=list)
    status: str | None = None
    current_allocation: float = 0.0
    adversarial: AdversarialResearchRecord | None = None


# 3f: sources that are genuinely MULTIPLE distinct observations sharing one
# source name (many future dates, many filings) — a real bug lived here
# once: naive dedup-by-source-name (correct for a single-value "latest
# reading" source like macro_cpi) silently kept only ONE of 22 real
# scheduled_macro_event rows and one of 45 regulatory_event_sec_edgar rows,
# discarding the rest. These are collected into their own lists instead.
MULTI_ENTRY_MACRO_SOURCES = {
    "scheduled_macro_event", "regulatory_event_sec_edgar", "regulatory_event_congress",
}
MAX_REGULATORY_EVENTS_SHOWN = 10


@dataclass
class JudgeContext:
    run_id: str
    as_of: datetime
    regime: MarketRegimeSnapshot | None
    regime_id: str | None
    unavailable_sources: list[str]
    assets: list[AssetJudgeContext]
    # 3f: shared GLOBAL_CRYPTO/MACRO-scope evidence (macro prints, global
    # liquidity, BTC correlations, regional premium) — one latest reading
    # per source, same "shared, not per-asset" treatment as regime.
    macro_evidence: dict[str, dict] = field(default_factory=dict)
    # 3f: the forward-looking macro-event calendar — genuinely multiple
    # future dates, never deduped down to one.
    scheduled_events: list[dict] = field(default_factory=list)
    # 3f: regulatory/policy events (SEC EDGAR + congress.gov) — genuinely
    # multiple filings/bills, capped to the most recent
    # MAX_REGULATORY_EVENTS_SHOWN rather than dumping all of them.
    regulatory_events: list[dict] = field(default_factory=list)


def build_judge_context(
    run_id: str,
    settings: Settings,
    candidates: list[ScreenedAsset],
    assets_by_id: dict[str, Asset],
    regime_repo: MarketRegimeRepository,
    evidence_repo: EvidenceObservationRepository,
    assessment_repo: ModelMarketAssessmentRepository,
    llm_analysis_repo: LLMAnalysisRepository,
    news_repo: NewsRepository,
    asset_status_repo: AssetStatusRepository,
    portfolio_position_repo: PortfolioPositionRepository,
    signal_source_repo: SignalSourceRepository,
    as_of: datetime | None = None,
    adversarial_repo: AdversarialResearchRepository | None = None,
) -> JudgeContext:
    # Optional override for 3e.1's replay, which needs the historical
    # cutoff date, not "now" — purely additive; every existing call site
    # (unchanged) still gets exactly today's behavior.
    as_of = as_of or datetime.now(UTC)
    regime = regime_repo.get_latest()

    # 3d's assessments are the Judge's core input (non-negotiable) — reuse
    # the most recent assessment RUN as a whole (not per-asset independently)
    # so every asset judged this run reflects the SAME assessment pass,
    # mirroring 3d's own "one shared regime" discipline one layer up.
    run_assessments = assessment_repo.get_latest_run_assessments()
    assessments_by_asset: dict[str, list[ModelMarketAssessmentRecord]] = defaultdict(list)
    for a in run_assessments:
        assessments_by_asset[a.asset_id].append(a)

    since = as_of - timedelta(hours=settings.news_lookback_hours)
    news_by_symbol = news_repo.get_recent_relevant_news(
        symbols=[c.symbol for c in candidates],
        since=since,
        until=as_of,
        limit_per_asset=settings.max_news_articles_per_asset,
    )

    positions = portfolio_position_repo.get_all()

    # Per PHASE3E_PROMPT.md task 1: "unavailable sources must appear as
    # UNAVAILABLE, not silently omitted." Disclosed once, run-wide (not
    # forced into a fabricated per-asset relevance mapping for every
    # registry entry) — most NOT_IMPLEMENTED/UNAVAILABLE sources are global
    # or asset-agnostic (CoinAnk, PlanB, macro, etc.), not per-asset facts.
    unavailable_sources = [
        s.name for s in signal_source_repo.get_all() if s.status != "OK"
    ]

    # 3f: shared macro/liquidity/regulatory backdrop. Defensive getattr —
    # 3e.1's replay passes a fake evidence repo that only implements
    # get_latest_by_asset (it never collected macro evidence at all), so
    # this degrades to empty there rather than requiring a matching change
    # to already-shipped replay code.
    macro_evidence: dict[str, dict] = {}
    scheduled_events_seen: dict[tuple, dict] = {}
    regulatory_events_seen: dict[tuple, dict] = {}
    get_global = getattr(evidence_repo, "get_latest_global_all", None)
    if get_global is not None:
        for obs in get_global():
            if obs.source == "scheduled_macro_event":
                key = (obs.payload.get("event"), obs.payload.get("scheduled_date"))
                scheduled_events_seen.setdefault(key, obs.payload)
            elif obs.source in MULTI_ENTRY_MACRO_SOURCES:
                key = (obs.source, obs.payload.get("accession_number") or obs.payload.get("title") or obs.observation_timestamp.isoformat())
                regulatory_events_seen.setdefault(key, {"source": obs.source, **obs.payload})
            else:
                macro_evidence.setdefault(
                    obs.source,
                    {
                        "payload": obs.payload,
                        "freshness": obs.freshness,
                        "decay_half_life_hours": obs.decay_half_life_hours,
                        "status": obs.status,
                    },
                )

    scheduled_events = sorted(scheduled_events_seen.values(), key=lambda e: e.get("scheduled_date") or "")
    regulatory_events = list(regulatory_events_seen.values())[:MAX_REGULATORY_EVENTS_SHOWN]

    asset_contexts = []
    for candidate in candidates:
        asset = assets_by_id.get(candidate.asset_id)
        if asset is None:
            continue

        assessments = assessments_by_asset.get(asset.id, [])
        if not assessments:
            continue  # no silent fallback — Judge needs 3d's assessments to reason at all

        single_obs, term_structure_obs = group_observations_by_multi_entry_source(
            evidence_repo.get_latest_by_asset(asset.id)
        )
        evidence_by_source: dict[str, dict] = {}
        for obs in single_obs:
            evidence_by_source.setdefault(
                obs.source,
                {
                    "payload": obs.payload,
                    "freshness": obs.freshness,
                    "decay_half_life_hours": obs.decay_half_life_hours,
                    "status": obs.status,
                },
            )
        term_structure_by_source: dict[str, list[dict]] = {
            source: [
                {
                    "payload": obs.payload,
                    "freshness": obs.freshness,
                    "decay_half_life_hours": obs.decay_half_life_hours,
                    "status": obs.status,
                }
                for obs in obs_list
            ]
            for source, obs_list in term_structure_obs.items()
        }

        status_entry = asset_status_repo.get_latest_status(asset.id)
        position = positions.get(asset.id)
        news_summaries = [
            f"[{a.published_at.isoformat()}] {a.title}: {a.summary or ''}"
            for a in news_by_symbol.get(candidate.symbol, [])
        ]

        adversarial = adversarial_repo.get_latest_by_asset(asset.id) if adversarial_repo else None

        asset_contexts.append(AssetJudgeContext(
            asset=asset,
            screened=candidate,
            snapshot=None,
            evidence_by_source=evidence_by_source,
            term_structure_by_source=term_structure_by_source,
            assessments=assessments,
            model_agreement=assessments[0].model_agreement,
            phase2_analyses=llm_analysis_repo.get_latest_by_asset(asset.id),
            news_summaries=news_summaries,
            adversarial=adversarial,
            status=status_entry.status if status_entry else None,
            current_allocation=position.current_allocation if position else 0.0,
        ))

    return JudgeContext(
        run_id=run_id,
        as_of=as_of,
        regime=regime,
        regime_id=regime.id if regime else None,
        unavailable_sources=unavailable_sources,
        assets=asset_contexts,
        macro_evidence=macro_evidence,
        scheduled_events=scheduled_events,
        regulatory_events=regulatory_events,
    )


SYSTEM_PROMPT_TEMPLATE = """\
You are the JUDGE in a paper-trading crypto research system — a deterministic \
synthesis step that converts independent evidence into ONE decision per \
asset. You are given, for each asset: 3b's deterministic screening factors \
and composite_factor_score, 3c's derivatives/on-chain evidence (with \
freshness and decay-half-life so you can weigh how stale each reading is), \
3d's independent multi-model assessments (already computed model_agreement \
across those models), 3f's adversarial bull/bear research and bull/base/bear \
scenarios (when available), Phase 2's own prior LLM analyses, recent news, \
and current portfolio status/allocation. Every asset shares the SAME market \
regime AND the same macro/global-liquidity/regulatory-calendar backdrop \
(3f) this run.

Non-negotiables:
- `confidence` must be YOUR OWN judgment, never an average of model \
confidence, model_agreement, source_agreement, or composite_factor_score. A \
high composite_factor_score with low confidence (or vice versa) is a \
legitimate output, not something to reconcile.
- `model_agreement` must be copied EXACTLY from the value given to you per \
asset below (it is already computed, not yours to recompute).
- `source_agreement`: YOUR OWN estimate of how much ALL evidence sources \
(not just the 3 models) agree in direction — composite_factor_score, \
derivatives/on-chain readings, news tone, and the model assessments \
together. Distinct from model_agreement; never equal to it by default.
- WATCH and NO_TRADE are DIFFERENT outcomes — do not default to WATCH for \
every hard case. Use WATCH when you DO have a real, coherent thesis and a \
specific condition you're waiting to resolve (e.g. "watch for funding to \
normalize before entering"). Use NO_TRADE when you have NO actionable view \
at all — evidence is too thin/stale to reason from, or so evenly balanced \
that stating any thesis (bullish, bearish, or "wait for X") would be \
manufacturing false precision. NO_TRADE is a real, reachable decision, not \
a hypothetical — if you find yourself never selecting it across a batch, \
reconsider whether some of your WATCH calls actually belong here instead.
- `target_allocation` is your UNCONSTRAINED view; a Risk Engine finalizes \
actual sizing afterward — do not self-limit it to what you assume the \
constraints are.
- If a source is listed below as UNAVAILABLE, you must not reason as if it \
exists or invent a value for it.
- A known scheduled event (e.g. a token unlock date) belongs in \
`invalidation_conditions` ("thesis holds unless X occurs before the \
horizon"), not buried in `key_risks`.
- Set `requires_review = true` whenever confidence is low, model_agreement \
or source_agreement is weak, or the recommended change is unusually large \
relative current exposure.
- `macro_sensitivity` is REQUIRED and must be YOUR OWN per-asset reasoning \
about how the shared macro/global-liquidity backdrop affects THIS SPECIFIC \
asset — never a blanket rule like "liquidity up = bullish for everything." \
A rising BTC-equity correlation can mean crypto trades as a macro risk \
asset (reducing diversification value) just as easily as it can mean \
anything directional about crypto itself — reason about which, for this \
asset, rather than assuming. If no macro evidence is available this run, \
say so explicitly here rather than omitting the field.
- If 3f's bull/bear research disagrees with the model assessments or the \
composite_factor_score, surface that tension explicitly in \
`key_evidence`/`contradictory_evidence` — do not silently prefer one.
- A dated regulatory/policy event near this asset's decision horizon \
belongs in `invalidation_conditions`, same treatment as a token unlock.

Respond with ONLY a single JSON object (no markdown fences, no commentary):

{{
  "decisions": [
    {{
      "asset": "<symbol, must match input exactly>",
      "decision": "BUY"|"HOLD"|"SELL"|"WATCH"|"NO_TRADE",
      "confidence": <0.0-1.0>,
      "target_allocation": <0.0-1.0>,
      "expected_return": <float>,
      "expected_alpha": <float>,
      "risk_score": <0.0-1.0>,
      "uncertainty": <0.0-1.0>,
      "model_agreement": <copied exactly from input>,
      "source_agreement": <0.0-1.0, your own estimate>,
      "investment_horizon_days": <int>,
      "key_evidence": ["..."],
      "contradictory_evidence": ["..."],
      "key_risks": ["..."],
      "invalidation_conditions": ["..."],
      "requires_review": true|false,
      "thesis": "...",
      "macro_sensitivity": "..."
    }}
  ]
}}

Prompt version: {prompt_version}\
"""


def render_prompt(context: JudgeContext, prompt_version: str) -> tuple[str, str]:
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(prompt_version=prompt_version)

    lines = [f"As of: {context.as_of.isoformat()}"]
    if context.regime is not None:
        lines.append(f"Market regime (shared, use exactly this value): {context.regime.regime}")
        lines.append(f"Regime inputs (BTC dominance, altseason index, halving-cycle position): {context.regime.inputs}")
    lines.append(
        "System-wide unavailable/not-yet-implemented sources (do not assume "
        f"these exist for any asset): {', '.join(context.unavailable_sources)}"
    )
    if context.macro_evidence:
        lines.append("Shared macro/global-liquidity/regulatory backdrop (3f), same for every asset:")
        for source, entry in context.macro_evidence.items():
            lines.append(
                f"  - {source}: status={entry['status']} freshness={entry['freshness']} "
                f"decay_half_life_hours={entry['decay_half_life_hours']} payload={entry['payload']}"
            )
    else:
        lines.append("Macro/global-liquidity/regulatory backdrop (3f): none available this run.")

    if context.scheduled_events:
        lines.append(f"Forward-looking macro-event calendar (3f), {len(context.scheduled_events)} scheduled events:")
        for event in context.scheduled_events:
            lines.append(
                f"  - {event.get('event')}: scheduled_date={event.get('scheduled_date')} "
                f"payload={event}"
            )
    else:
        lines.append("Forward-looking macro-event calendar (3f): none available this run.")

    if context.regulatory_events:
        lines.append(
            f"Regulatory/policy event calendar (3f), {len(context.regulatory_events)} events shown "
            f"(most recent {MAX_REGULATORY_EVENTS_SHOWN}):"
        )
        for event in context.regulatory_events:
            lines.append(f"  - {event}")
    else:
        lines.append("Regulatory/policy event calendar (3f): none available this run.")
    lines.append("")

    for ac in context.assets:
        lines.append(f"## {ac.asset.symbol} ({ac.asset.name})")
        lines.append(
            f"Portfolio status: {ac.status or 'UNKNOWN'} | "
            f"Current allocation: {ac.current_allocation:.2%}"
        )
        lines.append(
            f"Composite factor score (3b, deterministic, non-narrative): "
            f"{ac.screened.composite_factor_score}"
        )
        if ac.screened.anomaly_flag:
            lines.append(f"Screening anomaly flag (3b): {ac.screened.anomaly_reason}")

        if ac.evidence_by_source:
            lines.append("Derivatives/on-chain evidence (3c), with freshness/decay:")
            for source, entry in ac.evidence_by_source.items():
                lines.append(
                    f"  - {source}: status={entry['status']} freshness={entry['freshness']} "
                    f"decay_half_life_hours={entry['decay_half_life_hours']} "
                    f"payload={entry['payload']}"
                )

        if ac.term_structure_by_source:
            for source, entries in ac.term_structure_by_source.items():
                lines.append(
                    f"Futures term structure (3c), {source}, {len(entries)} distinct "
                    f"dated instruments (the full curve, not one point):"
                )
                for entry in entries:
                    lines.append(f"  - {entry['payload']}")

        if ac.assessments:
            model_agreement = ac.assessments[0].model_agreement
            lines.append(f"Model agreement across 3d's models for this asset (copy exactly): {model_agreement}")
            lines.append("3d model assessments:")
            for a in ac.assessments:
                lines.append(
                    f"  - {a.provider} ({a.model}): overall={a.overall_assessment} "
                    f"confidence(7/30/90d)={a.short_term_confidence}/{a.medium_term_confidence}/{a.long_term_confidence} "
                    f"expected_return(7/30/90d)={a.expected_return_7d}/{a.expected_return_30d}/{a.expected_return_90d} "
                    f"risk={a.risk_level}({a.risk_score}) thesis=\"{a.thesis}\""
                )

        if ac.adversarial is not None:
            bull = ac.adversarial.bull_case
            bear = ac.adversarial.bear_case
            lines.append("3f adversarial research:")
            lines.append(f"  - Bull thesis: {bull.get('thesis')}")
            lines.append(f"    Bull catalysts/evidence: {bull.get('catalysts')} / {bull.get('evidence')}")
            lines.append(f"  - Bear attack points (vs. this specific bull thesis): {bear.get('attack_points')}")
            lines.append(f"    Attacks: {bear.get('attacks_bull_point')}")
            lines.append(f"  - Scenarios (bull/base/bear): {ac.adversarial.scenarios}")

        if ac.phase2_analyses:
            lines.append("Phase 2 prior LLM analyses:")
            for pa in ac.phase2_analyses:
                lines.append(
                    f"  - {pa.provider}: action={pa.action} confidence={pa.confidence} "
                    f"thesis: bull=\"{pa.bull_case}\" bear=\"{pa.bear_case}\""
                )

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
