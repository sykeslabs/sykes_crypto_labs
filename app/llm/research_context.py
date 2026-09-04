import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.database.models import Asset
from app.database.repository import MarketSnapshotRepository, NewsRepository
from app.market_data.schemas import MarketSnapshot
from app.news.schemas import NewsArticle


@dataclass
class ResearchContext:
    """Everything sent to every LLM provider for one run — the same facts,
    so provider disagreement reflects reasoning, not different inputs.

    `as_of` is the hard cutoff: news published after this instant must never
    be included (see build_research_context), preventing lookahead bias.
    """

    run_id: str
    as_of: datetime
    assets: list[Asset]
    market_snapshots: dict[str, MarketSnapshot]  # asset_id -> latest snapshot
    news_by_symbol: dict[str, list[NewsArticle]]  # symbol -> recent relevant articles


def build_research_context(
    run_id: str,
    settings: Settings,
    assets: list[Asset],
    snapshot_repo: MarketSnapshotRepository,
    news_repo: NewsRepository,
) -> ResearchContext:
    as_of = datetime.now(UTC)

    market_snapshots: dict[str, MarketSnapshot] = {}
    for asset in assets:
        snapshot = snapshot_repo.get_latest_snapshot(asset.id)
        if snapshot is not None:
            market_snapshots[asset.id] = snapshot

    since = as_of - timedelta(hours=settings.news_lookback_hours)
    news_by_symbol = news_repo.get_recent_relevant_news(
        symbols=[a.symbol for a in assets],
        since=since,
        until=as_of,
        limit_per_asset=settings.max_news_articles_per_asset,
    )

    return ResearchContext(
        run_id=run_id,
        as_of=as_of,
        assets=assets,
        market_snapshots=market_snapshots,
        news_by_symbol=news_by_symbol,
    )


SYSTEM_PROMPT_TEMPLATE = """\
You are a cryptocurrency investment analyst providing structured, independent \
analysis for a paper-trading research system. You will be given current market \
data and recent news for a set of crypto assets, as of a fixed cutoff timestamp.

Analyze EVERY asset listed and respond with ONLY a single JSON object (no markdown \
fences, no commentary before or after) matching exactly this shape:

{{
  "analyses": [
    {{
      "asset_symbol": "<symbol, must match one from the input exactly>",
      "action": "BUY" | "HOLD" | "SELL",
      "confidence": <float 0.0-1.0>,
      "target_allocation": <float 0.0-1.0, fraction of total portfolio>,
      "investment_horizon": "<short/medium/long term description>",
      "thesis": "<concise overall thesis>",
      "bull_case": "<strongest case for>",
      "bear_case": "<strongest case against>",
      "catalysts": ["<upcoming catalyst>", ...],
      "risks": ["<key risk>", ...],
      "invalidation_conditions": ["<what would prove this thesis wrong>", ...]
    }}
  ]
}}

Include exactly one entry per asset provided. Base your analysis only on the \
data given — do not assume information you were not given, and do not reference \
events after the stated cutoff timestamp. If the available data is genuinely \
insufficient to support a BUY or SELL, respond HOLD with low confidence rather \
than inventing a rationale.

Prompt version: {prompt_version}\
"""


def render_prompt(context: ResearchContext, prompt_version: str) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt)."""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(prompt_version=prompt_version)

    lines = [f"As of: {context.as_of.isoformat()}", ""]
    for asset in context.assets:
        lines.append(f"## {asset.symbol} ({asset.name})")
        snapshot = context.market_snapshots.get(asset.id)
        if snapshot is None:
            lines.append("No current market data available.")
        else:
            lines.append(
                f"Price: ${snapshot.price} | Market cap: {snapshot.market_cap} "
                f"| 24h volume: {snapshot.volume_24h}"
            )
            lines.append(
                f"Change: 24h {snapshot.price_change_24h}% | "
                f"7d {snapshot.price_change_7d}% | 30d {snapshot.price_change_30d}%"
            )
            lines.append(f"Snapshot as of: {snapshot.timestamp.isoformat()}")

        articles = context.news_by_symbol.get(asset.symbol, [])
        if articles:
            lines.append("Recent news:")
            for article in articles:
                lines.append(
                    f"  - [{article.published_at.isoformat()}] ({article.source}) "
                    f"{article.title}: {article.summary or ''}"
                )
        else:
            lines.append("Recent news: none found.")
        lines.append("")

    user_prompt = "\n".join(lines)
    return system_prompt, user_prompt


def compute_input_hash(system_prompt: str, user_prompt: str) -> str:
    return hashlib.sha256(f"{system_prompt}\n{user_prompt}".encode("utf-8")).hexdigest()
