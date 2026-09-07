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
from app.judge.schemas import JudgeDecisionRecord


class LiveFactorSnapshot(BaseModel):
    """Phase 5b: a genuinely live, request-time recomputation of the same
    six screening factors `screened_universe` stores, using the same pure
    functions (`app/market_data/factors.py`) real screening runs use —
    display-only, informative context for "how much has this changed since
    the stored snapshot", never fed into composite_factor_score, Layer 2
    candidate promotion, or any Judge/Risk Engine/Portfolio Construction
    computation, all of which stay anchored to the stored screening run
    (see `HoldingsEntryView`'s live-vs-stored-price docstring for the same
    reasoning applied to prices). `None` per-field when that piece
    genuinely isn't available right now (e.g. neither Binance nor Coinbase
    lists this symbol) — never fabricated."""

    symbol: str
    momentum_7d: float | None
    momentum_30d: float | None
    relative_strength_30d: float | None
    volatility_30d: float | None
    drawdown_30d: float | None
    volume_24h: float | None
    volatility_drawdown_source: str
    computed_at: datetime


class JudgeDecisionView(BaseModel):
    """A `JudgeDecisionRecord`, joined with its asset's `symbol` — that
    record only stores `asset_id` (a raw UUID), the same class of gap
    already found and fixed for holdings/portfolio-state (Phase 5b).
    `decision` nests the existing record whole rather than duplicating its
    fields, per this file's own convention."""

    symbol: str
    decision: JudgeDecisionRecord


class HoldingsEntryView(BaseModel):
    """One `holdings_ledger` row, joined with the asset's `symbol` — the
    join `HoldingsLedgerEntry` doesn't do on its own (it only stores
    `asset_id`). `symbol` is `"CASH"` for the reserved cash line
    (`asset_id=None`), never a raw UUID a viewer would have to look up by
    hand. `allocation` is the same real fraction-of-total-portfolio-value
    `compute_current_allocations` (Phase 5a) feeds into Portfolio
    Construction — computed only for the current-state endpoint (`GET
    /holdings`), left `None` for `/holdings/history` rows, where "this
    entry's share of the CURRENT total" isn't a meaningful question for a
    superseded historical row. `value_usd` is this entry's real dollar
    value right now (`quantity` directly for the `CASH` row, `quantity *
    current price` for everything else) — Phase 5b's real backend addition
    (see `doc/prompts/PHASE5B_PROMPT.md`'s "Open questions resolved" item
    4), since a total portfolio value cannot be derived client-side from
    `allocation` (a fraction) alone without a fragile back-solve. `None`
    when a real current price isn't available for that asset (never a
    fabricated 0), and always `None` for `/holdings/history` rows, same
    reasoning as `allocation`. `price_usd` is the same real current price
    used to compute `value_usd` — always `None` for the `CASH` row (a
    price-per-unit isn't a meaningful concept for a stated dollar amount).
    `price_as_of` is that price's own `market_snapshots.timestamp` — this
    is the last *collected* price (`python -m app.main` is a manual,
    periodic batch step; there is no live price stream), never a live
    real-time quote, so the UI must show this timestamp alongside the
    price rather than implying freshness it doesn't have. `live_price_usd`/
    `live_price_as_of`/`live_price_source` are a genuinely live spot price
    fetched from Binance (falling back to Coinbase) at request time — by
    explicit user choice, kept entirely separate from `price_usd`/
    `value_usd`/`allocation` above, which stay based on the stored
    snapshot so the real pipeline (Risk Engine, Portfolio Construction)
    and the dashboard always agree on those numbers. `None` when neither
    venue lists the asset (e.g. `CASH`) — never fabricated.

    `purchased_at`/`transaction_type` pass through the underlying
    transaction unchanged (Phase 5b's transactional model — see
    `HoldingsLedgerEntry`). `cost_per_unit`/`unrealized_pnl_usd`/
    `unrealized_pnl_pct` are computed only on the aggregated current-state
    view (`GET /holdings`), never on `/holdings/history` rows, since a
    single historical transaction's own cost basis isn't "the" cost basis
    once other transactions for the same asset exist — only the
    aggregated position has one real weighted-average cost basis. P&L is
    computed against `value_usd` (the stored/collected price), matching
    every other number on this row — never against the live spot price,
    per the same reasoning as `price_usd` vs `live_price_usd`. `None`
    whenever no cost basis was ever entered for that position (never a
    fabricated 0)."""

    id: str | None
    asset_id: str | None
    symbol: str
    quantity: float
    cost_basis_usd: float | None
    recorded_at: datetime
    purchased_at: datetime | None = None
    transaction_type: str = "BUY"
    allocation: float | None = None
    value_usd: float | None = None
    price_usd: float | None = None
    price_as_of: datetime | None = None
    cost_per_unit: float | None = None
    unrealized_pnl_usd: float | None = None
    unrealized_pnl_pct: float | None = None
    live_price_usd: float | None = None
    live_price_as_of: datetime | None = None
    live_price_source: str | None = None


class PortfolioStateEntry(BaseModel):
    """One current holding, joined with its most recent decision's tracked
    outcome (mark-to-mid vs. net-of-costs, `assumed_fill_method`) — the
    join `portfolio_positions` doesn't do on its own. `regime_label`
    (Phase 5b) is a second join `outcome` doesn't do on its own either:
    `outcome.regime_at_decision` is a raw `market_regime_snapshots.id`,
    never the human-readable regime itself — a real gap found live when
    the dashboard first rendered a raw UUID. `None` when there's no
    outcome, or when the FK genuinely can't be resolved (e.g. the
    documented regime_at_decision-is-NULL persistence gap on backfilled
    decisions — never a fabricated label). `price_usd` (Phase 5b) is this
    asset's real current price, looked up the same way `/holdings` does —
    `None` when no real current price is available (never fabricated).
    `price_as_of` is that price's own snapshot timestamp — the last
    *collected* price, never a live quote. `live_price_usd`/
    `live_price_as_of`/`live_price_source` are a genuinely live spot price
    (see `HoldingsEntryView`'s docstring for the full reasoning)."""

    asset_id: str
    symbol: str
    current_allocation: float
    last_decision_id: str | None
    updated_at: datetime | None
    outcome: DecisionOutcome | None = None
    regime_label: str | None = None
    price_usd: float | None = None
    price_as_of: datetime | None = None
    live_price_usd: float | None = None
    live_price_as_of: datetime | None = None
    live_price_source: str | None = None


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
