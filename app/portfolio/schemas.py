from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PortfolioPosition(BaseModel):
    """One row of `portfolio_positions` — current state of the paper book.
    No Phase 1/2 seed: `assets.in_asset` was never a sized position, so
    every asset starts at allocation 0 until Portfolio Construction first
    assigns one (see migrations/0007)."""

    asset_id: str
    current_allocation: float = 0.0
    last_decision_id: str | None = None
    updated_at: datetime | None = None


class PortfolioAllocationChange(BaseModel):
    """One row of `portfolio_allocation_changes` — an append-only log of
    every STRATEGY target change, so MAX_WEEKLY_TURNOVER can sum real
    strategy-driven changes over a trailing window (current state alone
    can't answer that).

    `previous_allocation`/`new_allocation` are the system's own target
    (portfolio_positions.current_allocation) before/after this event --
    NOT real holdings. `actual_allocation_before` is the real,
    ground-truth holdings-based allocation at the same moment, kept
    alongside for audit visibility only (never summed into turnover). A
    real bug fixed 2026-09-14: before this, `previous_allocation` WAS real
    holdings, so a manual `/holdings` trade that moved real holdings away
    from the system's own last target got counted as strategy turnover the
    next time the Judge revisited that asset -- see
    `RiskEngine._strategy_turnover_delta`'s docstring for the full real
    incident and backtest evidence.

    `baseline_semantics` disambiguates rows written under the OLD (real
    holdings) vs NEW (system target) meaning of `previous_allocation` --
    existing rows from before 2026-09-14 are annotated `"actual_holdings"`
    (their real, unchanged original meaning; never rewritten), every new
    row is `"system_target"`. Never delete or renumber old rows to make the
    turnover history look cleaner -- they are genuine historical fact under
    their own real semantics.

    `change_reason` disambiguates WHY the target moved -- `"strategy"` for
    a real sizing decision (BUY/SELL/HOLD, or a capped BUY), `"risk_control"`
    for a WATCH/NO_TRADE correction (`RiskEngine.size_one`'s
    `min(current_allocation, max_single_asset_allocation)` clamp). Real bug
    fixed 2026-09-17: `_strategy_turnover_delta` already treats
    WATCH/NO_TRADE as zero strategy turnover at decision time, but that
    exemption was never persisted, so `get_turnover_since` silently
    re-counted it as real turnover on every later read -- see
    migrations/0021 for the historical backfill and the full incident.
    Always set from the already-gated `SizedDecision.decision` at
    construction time -- never reconstructed later from
    `judge_decisions.decision` (the raw, pre-confidence-gate value)."""

    id: str | None = None
    asset_id: str
    run_id: str
    decision_id: str | None
    previous_allocation: float
    new_allocation: float
    actual_allocation_before: float | None = None
    baseline_semantics: str = "system_target"
    change_reason: Literal["strategy", "risk_control"] = "strategy"
    changed_at: datetime

    def to_row(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "previous_allocation": self.previous_allocation,
            "new_allocation": self.new_allocation,
            "actual_allocation_before": self.actual_allocation_before,
            "baseline_semantics": self.baseline_semantics,
            "change_reason": self.change_reason,
            "changed_at": self.changed_at.isoformat(),
        }


class TurnoverCapEvent(BaseModel):
    """One row of `turnover_cap_events` -- a real, persisted, dashboard-
    visible record of every run where MAX_WEEKLY_TURNOVER capped at least
    one proposed position change. Found live 2026-09-14: before this,
    `RiskEngine.apply_turnover_cap` capping every proposed change (e.g. a
    full revert when the week's real turnover was already at/over budget)
    was only ever logged via a stdout `logger.warning` -- never persisted
    anywhere, never surfaced on the dashboard, and this project has no log
    file at all (see app/logging_config.py), so a fully-blocked run was
    completely invisible after the fact. `fully_blocked=True` means EVERY
    proposed change this run was reverted (remaining_budget was ~0);
    `False` means some changes still went through at a scaled-down size.
    `capped_symbols` names exactly which assets had a proposed change
    reduced or reverted this run."""

    id: str | None = None
    run_id: str
    occurred_at: datetime
    turnover_used_this_week: float
    max_weekly_turnover: float
    remaining_budget: float
    fully_blocked: bool
    capped_symbols: list[str]

    def to_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "occurred_at": self.occurred_at.isoformat(),
            "turnover_used_this_week": self.turnover_used_this_week,
            "max_weekly_turnover": self.max_weekly_turnover,
            "remaining_budget": self.remaining_budget,
            "fully_blocked": self.fully_blocked,
            "capped_symbols": self.capped_symbols,
        }


class HoldingsLedgerEntry(BaseModel):
    """One row of `holdings_ledger` (Phase 5a/5b) — a real transaction, not
    a snapshot: `asset_id=None` is the reserved cash line (`quantity` is
    then a stated USD amount directly, not asset units, and always an
    absolute total — cash is never summed across rows the way real-asset
    transactions are). Append-only. Never a decision/target_allocation
    field of any kind — this is factual data entry only, see the
    non-negotiable in PHASE5A_PROMPT.md.

    `transaction_type` (Phase 5b): `"BUY"` adds `quantity` to that asset's
    running position, `"SELL"` subtracts it — explicit and auditable
    rather than an implicit sign on `quantity`, which stays non-negative
    either way (see `aggregate_current_holdings`). Defaults to `"BUY"`,
    accurate for every row entered before this field existed.

    `purchased_at` (Phase 5b): the real date this was bought/sold at this
    price — distinct from `recorded_at` (when the row was entered into
    the ledger, which may be well after the fact). `None` for rows entered
    before this field existed — never a fabricated backfilled date."""

    id: str | None = None
    asset_id: str | None = None
    quantity: float
    cost_basis_usd: float | None = None
    recorded_at: datetime
    purchased_at: datetime | None = None
    transaction_type: Literal["BUY", "SELL"] = "BUY"

    def to_row(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "quantity": self.quantity,
            "cost_basis_usd": self.cost_basis_usd,
            "recorded_at": self.recorded_at.isoformat(),
            "purchased_at": self.purchased_at.isoformat() if self.purchased_at else None,
            "transaction_type": self.transaction_type,
        }
