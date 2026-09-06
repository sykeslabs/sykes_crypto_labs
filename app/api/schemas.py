"""Phase 5: response models used ONLY where no existing Pydantic schema
fits — composed/join views over already-existing schemas, never a parallel
redefinition of fields those schemas already own. Every field here either
nests an existing schema directly or is a small piece of view-composition
metadata (e.g. a computed count), consistent with the non-negotiable to
reuse existing schemas as FastAPI response models.
"""

from datetime import datetime

from pydantic import BaseModel

from app.benchmarks.schemas import DecisionOutcome


class PortfolioStateEntry(BaseModel):
    """One current holding, joined with its most recent decision's tracked
    outcome (mark-to-mid vs. net-of-costs, `assumed_fill_method`) — the
    join `portfolio_positions` doesn't do on its own."""

    asset_id: str
    symbol: str
    current_allocation: float
    last_decision_id: str | None
    updated_at: datetime | None
    outcome: DecisionOutcome | None = None


class CalibrationSummary(BaseModel):
    """Real, live-computed counts and figures — never a merged/averaged
    single number across backfilled/live or resolved/unresolved. Absent
    or None fields mean genuinely not-yet-computable, not zero."""

    resolved_backfilled_count: int
    resolved_live_count: int
    unresolved_backfilled_count: int
    unresolved_live_count: int
    directional_sample_size: int
    hit_rate: float | None
    brier_score: float | None
    sharpe_decision_level: float | None
    deflated_sharpe_ratio: float | None
    by_regime_note: str
    held_out_window_note: str


class CostTableBreakdown(BaseModel):
    table: str
    cost_usd: str


class CostWindowReport(BaseModel):
    since: datetime
    total_usd: str
    cap_usd: str
    remaining_usd: str
    by_table: list[CostTableBreakdown]


class CostSummary(BaseModel):
    daily: CostWindowReport
    monthly: CostWindowReport
    note: str = (
        "This is the app's own tracked spend via COST_TRACKED_TABLES, not a "
        "live provider-billing balance -- the two are not guaranteed to match "
        "(see README's Phase 3f OpenRouter account-vs-key-limit finding)."
    )
