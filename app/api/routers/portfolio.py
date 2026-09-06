from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import get_asset_repo, get_decision_outcome_repo, get_portfolio_position_repo
from app.api.schemas import PortfolioStateEntry
from app.database.repository import AssetRepository, DecisionOutcomeRepository, PortfolioPositionRepository
from app.portfolio.schemas import PortfolioPosition

router = APIRouter(prefix="/portfolio", tags=["portfolio"], dependencies=[Depends(verify_api_key)])


@router.get("/positions", response_model=list[PortfolioPosition])
def get_positions(repo: PortfolioPositionRepository = Depends(get_portfolio_position_repo)) -> list[PortfolioPosition]:
    """Raw current holdings, exactly as stored."""
    return list(repo.get_all().values())


@router.get("/state", response_model=list[PortfolioStateEntry])
def get_portfolio_state(
    position_repo: PortfolioPositionRepository = Depends(get_portfolio_position_repo),
    asset_repo: AssetRepository = Depends(get_asset_repo),
    outcome_repo: DecisionOutcomeRepository = Depends(get_decision_outcome_repo),
) -> list[PortfolioStateEntry]:
    """Current holdings joined with each position's most recent decision's
    tracked outcome — mark-to-mid vs. net-of-costs and `assumed_fill_method`
    surfaced explicitly per fill (Phase 4 built this specifically to make a
    previously-hidden assumption visible; this view does not hide it
    again). `outcome` is `null` when the decision hasn't resolved yet, or
    when there's no `last_decision_id` at all — an honest empty state, not
    an error."""
    assets_by_id = {a.id: a for a in asset_repo.get_active_assets()}
    positions = position_repo.get_all()

    entries = []
    for asset_id, position in positions.items():
        if position.current_allocation <= 0:
            continue
        asset = assets_by_id.get(asset_id)
        if asset is None:
            continue
        outcome = (
            outcome_repo.get_by_decision_id(position.last_decision_id)
            if position.last_decision_id else None
        )
        entries.append(PortfolioStateEntry(
            asset_id=asset_id, symbol=asset.symbol, current_allocation=position.current_allocation,
            last_decision_id=position.last_decision_id, updated_at=position.updated_at, outcome=outcome,
        ))
    return entries
