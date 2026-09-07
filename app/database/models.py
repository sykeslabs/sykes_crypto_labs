from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Asset(BaseModel):
    id: str
    symbol: str
    name: str
    coingecko_id: str
    coinmarketcap_id: str | None = None
    active: bool
    in_asset: bool
    created_at: datetime


AssetStatusValue = Literal["HELD", "WATCHLIST", "CANDIDATE", "REJECTED"]


class AssetStatusHistory(BaseModel):
    """One row of `asset_status_history` — an append-only record of a status
    change. The "current" status for an asset is the row with the latest
    `changed_at`; `assets.active`/`assets.in_asset` are unrelated and
    unaffected by this.
    """

    id: str | None = None
    asset_id: str
    status: AssetStatusValue
    reason: str | None = None
    changed_at: datetime
    created_at: datetime | None = None

    def to_row(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "status": self.status,
            "reason": self.reason,
            "changed_at": self.changed_at.isoformat(),
        }


SignalSourceStatus = Literal["OK", "UNAVAILABLE", "UNKNOWN", "NOT_IMPLEMENTED"]


class SignalSource(BaseModel):
    """One row of the `signal_sources` registry."""

    name: str
    status: SignalSourceStatus
    last_checked_at: datetime | None = None
    notes: str | None = None
    created_at: datetime | None = None
