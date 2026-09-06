"""Phase 5a: the ground-truth "what do I actually own" write endpoint —
the ONE narrow exception to Phase 5's otherwise strictly read-only API.
Ground truth only, never a decision override (see PHASE5A_PROMPT.md's own
non-negotiable): the request schema below has no `decision`,
`target_allocation`, or any other Judge/Risk Engine/Portfolio Construction
output field, by construction, not by convention alone.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import verify_api_key
from app.api.dependencies import get_asset_repo, get_holdings_ledger_repo
from app.database.repository import AssetRepository, HoldingsLedgerRepository
from app.portfolio.schemas import HoldingsLedgerEntry

router = APIRouter(prefix="/holdings", tags=["holdings"], dependencies=[Depends(verify_api_key)])


class HoldingsEntryRequest(BaseModel):
    """`asset_id=None` is the reserved cash line — `quantity` is then a
    stated USD amount directly, not asset units. No decision/allocation
    field exists here or anywhere in this request; adding one would be a
    non-negotiable violation, not a feature."""

    asset_id: str | None = None
    quantity: float = Field(ge=0, description="Asset units, or USD amount when asset_id is null (cash).")
    cost_basis_usd: float | None = Field(default=None, ge=0)


@router.post("", response_model=HoldingsLedgerEntry, status_code=201)
def record_holding(
    entry: HoldingsEntryRequest,
    asset_repo: AssetRepository = Depends(get_asset_repo),
    ledger_repo: HoldingsLedgerRepository = Depends(get_holdings_ledger_repo),
) -> HoldingsLedgerEntry:
    """Append-only: this always INSERTS a new row, never updates or
    deletes a prior one — editing a position is a new entry with a newer
    `recorded_at`; removing one is a new entry with `quantity=0`. "What did
    I hold as of date T" stays answerable via `/holdings/history`."""
    if entry.asset_id is not None:
        asset = asset_repo.get_by_id(entry.asset_id)
        if asset is None:
            raise HTTPException(
                status_code=422,
                detail=f"asset_id '{entry.asset_id}' is not a tracked asset — it must already exist in the assets table.",
            )

    record = HoldingsLedgerEntry(
        asset_id=entry.asset_id, quantity=entry.quantity, cost_basis_usd=entry.cost_basis_usd,
        recorded_at=datetime.now(UTC),
    )
    ledger_repo.insert(record)
    return record


@router.get("", response_model=list[HoldingsLedgerEntry])
def get_current_holdings(repo: HoldingsLedgerRepository = Depends(get_holdings_ledger_repo)) -> list[HoldingsLedgerEntry]:
    """The latest row per asset (including the cash line) — the current
    ground-truth holdings state Portfolio Construction actually reasons
    against."""
    return repo.get_latest_holdings()


@router.get("/history", response_model=list[HoldingsLedgerEntry])
def get_holdings_history(
    asset_id: str | None = None, cash: bool = False,
    repo: HoldingsLedgerRepository = Depends(get_holdings_ledger_repo),
) -> list[HoldingsLedgerEntry]:
    """Full append-only history, newest first — proves "what did I hold as
    of date T" is genuinely answerable, not just the latest snapshot.
    `cash=true` returns just the cash line's history; `asset_id=<id>`
    returns just that asset's; omitting both returns every entry ever
    recorded (cash and every asset)."""
    if cash:
        return repo.get_history(None)
    if asset_id is not None:
        return repo.get_history(asset_id)
    return repo.get_all_history()
