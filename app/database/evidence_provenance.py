"""The generic evidence-provenance shape every future evidence-source table
(3b, 3c, 3f) reuses. Not a standalone database table itself — each concrete
source table composes these columns alongside its own source-specific
payload (see migrations/0003_phase3a_universe_provenance.sql for the
authoritative column list and the matching SQL comment block).
"""

from datetime import datetime
from typing import Iterable, Literal, Protocol, TypedDict

from pydantic import BaseModel

Scope = Literal["ASSET", "GLOBAL_CRYPTO", "MACRO"]
Freshness = Literal["REALTIME", "RECENT", "STALE", "UNKNOWN"]
EvidenceStatus = Literal["OK", "UNAVAILABLE", "UNKNOWN"]

# Asset-scoped sources that genuinely emit MULTIPLE distinct observations
# sharing one source name within a single collection run (one row per dated
# futures instrument) — a real bug lived here once (found during 3g's
# point-in-time audit): naive dedup-by-source-name
# (`evidence_by_source.setdefault(obs.source, ...)`, correct for genuinely
# single-valued sources like `binance_funding_rate`) silently kept only one
# arbitrary dated-futures instrument per asset per run, discarding the rest
# of the term-structure curve — the entire analytical point of "term
# structure" is its shape across expiries, not one point on it. Verified
# live: `deribit_futures_term_structure` alone had up to 12 distinct BTC
# instruments collapsed to 1. See README's Phase 3g section.
MULTI_ENTRY_ASSET_SOURCES: set[str] = {
    "binance_futures_term_structure",
    "deribit_futures_term_structure",
}

# Starting freshness-decay half-lives per source *type* (hours) — not per
# observation. Approximate, meant to be refined as each source is actually
# built (3b/3c/3f); these are only the ones already known at 3a time.
DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE: dict[str, float] = {
    # Phase 1 — price moves fast; a snapshot is meaningfully stale within a
    # couple of hours.
    "coingecko_price": 2.0,
    # Phase 2 — a news story matters for hours, occasionally into the next
    # day, rarely longer.
    "news": 18.0,
    # 3f — a macro print (CPI, NFP, Fed decision) stays relevant until the
    # next release supersedes it; 30 days is a placeholder for "about a
    # month," refined once 3f actually builds this.
    "macro": 720.0,
    # 3c — funding settles every 8h on Binance; the current rate is most
    # relevant until roughly the next settlement.
    "binance_funding_rate": 8.0,
    # 3c — open interest (either venue) drifts over the course of a day.
    "open_interest": 12.0,
    # 3c — the futures curve/basis moves with spot but the annualized carry
    # yield reflects a slower-moving term-structure expectation.
    "futures_term_structure": 24.0,
    # 3c — options IV/put-call ratio move intraday but not as fast as spot.
    "options_data": 12.0,
    # 3c — derived from IV, same cadence.
    "volatility_risk_premium": 12.0,
    # 3c — CFTC's COT report is published weekly and reflects the prior
    # Tuesday's close — stale by design, not a bug. Half of the ~7-day
    # publication cycle.
    "cftc_cot": 84.0,
    # 3c — protocol/chain TVL and stablecoin supply both move on a roughly
    # daily cadence.
    "defillama_tvl": 24.0,
    "stablecoin_supply": 24.0,
    # 3c — a large-transfer-count proxy is close to real-time.
    "etherscan_large_transfer": 6.0,
    # 3f — global liquidity proxies (M2/Fed balance sheet/reverse repo) move
    # on a weekly-to-monthly cadence, same standing as ordinary macro prints.
    "global_liquidity": 720.0,
    # 3f — a known-in-advance scheduled release date (CPI/PCE/NFP) stays
    # relevant until that date passes, not a decaying observation in the
    # usual sense; reuses the macro half-life as a simple, documented
    # convention rather than inventing a new decay model for a future fact.
    "scheduled_macro_event": 720.0,
    # 3f — regional exchange price premiums move with spot price, close to
    # real-time, same cadence as an ordinary price feed.
    "regional_exchange_premium": 2.0,
    # 3f — a regulatory/policy event's relevance persists for weeks after
    # filing/introduction, longer than an ordinary news story but shorter
    # than a multi-month macro trend.
    "regulatory_event": 336.0,
    # 3i — entity-flow (smart-money netflow) and per-token network-usage
    # activity both change with each new on-chain transaction, matching
    # Nansen's own 24h-window netflow cadence — hours-scale, same standing
    # as ordinary derivatives/on-chain readings (3c).
    "entity_flow_intelligence": 24.0,
    "network_fundamentals_usage": 24.0,
    # 3i — developer activity (commit velocity, contributor count) is
    # inherently slow-moving: a single day's commit count is nearly
    # meaningless on its own, and a real change in trend plays out over
    # weeks, not hours — reuses the macro/regulatory-event-scale half-life
    # as a simple, documented convention (per this project's own precedent
    # in 3f) rather than inventing a new decay model.
    "developer_activity": 720.0,
}


class EvidenceProvenanceFields(BaseModel):
    """Shared provenance columns. Compose into a concrete source's own
    Pydantic schema (don't subclass unless the source truly adds nothing
    else) when building 3b/3c/3f tables.
    """

    source: str
    asset_id: str | None = None  # null for GLOBAL_CRYPTO/MACRO scope
    scope: Scope
    observation_timestamp: datetime
    publication_timestamp: datetime | None = None
    retrieval_timestamp: datetime
    timeframe: str | None = None
    is_revision_of: str | None = None  # FK (by id) to an earlier row this corrects
    freshness: Freshness
    decay_half_life_hours: float
    status: EvidenceStatus
    payload: dict


class _RowWithRetrieval(TypedDict):
    retrieval_timestamp: datetime


def latest_value_as_of[T: _RowWithRetrieval](rows: list[T], as_of: datetime) -> T | None:
    """Given rows sharing one (source, asset_id) key, each with a
    `retrieval_timestamp`, returns the one that was the latest known value at
    time `as_of` — the point-in-time-correct resolution for revisable
    evidence (see the point-in-time-integrity non-negotiable in
    PHASE3A_PROMPT.md).

    A later correction is stored as a new row (linked via `is_revision_of` to
    the row it corrects), so selecting the latest row by `retrieval_timestamp`
    that is <= `as_of` already reflects "what was known then" — no need to
    walk the `is_revision_of` chain by hand.

    Equivalent live query against any concrete evidence table:

        select * from <evidence_table>
        where source = :source and asset_id = :asset_id
          and retrieval_timestamp <= :as_of
        order by retrieval_timestamp desc
        limit 1;
    """
    candidates = [r for r in rows if r["retrieval_timestamp"] <= as_of]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["retrieval_timestamp"])


class _SourceTimeframeObservation(Protocol):
    source: str
    timeframe: str | None


def group_observations_by_multi_entry_source[T: _SourceTimeframeObservation](
    observations: Iterable[T],
) -> tuple[list[T], dict[str, list[T]]]:
    """Splits one asset's evidence_observations rows (already ordered
    newest-first by `retrieval_timestamp`, as `get_latest_by_asset` returns)
    into `(single_value_observations, multi_value_observations_by_source)`.

    `single_value_observations` is every row from a source NOT in
    `MULTI_ENTRY_ASSET_SOURCES` — callers still dedupe these by source name
    (first/latest occurrence wins), which is correct because such a source
    only ever has one current reading.

    `multi_value_observations_by_source` groups a `MULTI_ENTRY_ASSET_SOURCE`'s
    rows by source name, deduped by `(source, timeframe)` (the dated-futures
    instrument identifier) rather than collapsed to one row — this is the
    actual fix: every distinct instrument survives, not just whichever one
    a naive `setdefault(obs.source, ...)` happened to see first.
    """
    single_value_observations: list[T] = []
    multi_value_seen: dict[tuple[str, str | None], T] = {}
    for obs in observations:
        if obs.source in MULTI_ENTRY_ASSET_SOURCES:
            multi_value_seen.setdefault((obs.source, obs.timeframe), obs)
        else:
            single_value_observations.append(obs)

    multi_value_by_source: dict[str, list[T]] = {}
    for (source, _timeframe), obs in multi_value_seen.items():
        multi_value_by_source.setdefault(source, []).append(obs)
    return single_value_observations, multi_value_by_source
