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
