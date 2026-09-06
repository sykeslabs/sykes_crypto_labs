from datetime import datetime

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
    every allocation change, so MAX_WEEKLY_TURNOVER can sum real changes over
    a trailing window (current state alone can't answer that)."""

    id: str | None = None
    asset_id: str
    run_id: str
    decision_id: str | None
    previous_allocation: float
    new_allocation: float
    changed_at: datetime

    def to_row(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "previous_allocation": self.previous_allocation,
            "new_allocation": self.new_allocation,
            "changed_at": self.changed_at.isoformat(),
        }


class HoldingsLedgerEntry(BaseModel):
    """One row of `holdings_ledger` (Phase 5a) — the ground-truth "what do
    I actually own" input, append-only. `asset_id=None` is the reserved
    cash line (`quantity` is then a stated USD amount directly, not asset
    units). Never a decision/target_allocation field of any kind — this is
    factual data entry only, see the non-negotiable in PHASE5A_PROMPT.md."""

    id: str | None = None
    asset_id: str | None = None
    quantity: float
    cost_basis_usd: float | None = None
    recorded_at: datetime

    def to_row(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "quantity": self.quantity,
            "cost_basis_usd": self.cost_basis_usd,
            "recorded_at": self.recorded_at.isoformat(),
        }
