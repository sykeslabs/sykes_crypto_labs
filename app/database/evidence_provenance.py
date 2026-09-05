"""The generic evidence-provenance shape every future evidence-source table
(3b, 3c, 3f) reuses. Not a standalone database table itself — each concrete
source table composes these columns alongside its own source-specific
payload (see migrations/0003_phase3a_universe_provenance.sql for the
authoritative column list and the matching SQL comment block).
"""

from datetime import datetime
from typing import Literal, TypedDict

from pydantic import BaseModel

Scope = Literal["ASSET", "GLOBAL_CRYPTO", "MACRO"]
Freshness = Literal["REALTIME", "RECENT", "STALE", "UNKNOWN"]
EvidenceStatus = Literal["OK", "UNAVAILABLE", "UNKNOWN"]

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
