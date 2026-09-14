from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import (
    get_asset_repo,
    get_binance_client,
    get_coinbase_client,
    get_decision_outcome_repo,
    get_market_snapshot_repo,
    get_portfolio_position_repo,
    get_regime_repo,
    get_turnover_cap_event_repo,
)
from app.api.schemas import PortfolioStateEntry
from app.database.repository import (
    AssetRepository,
    DecisionOutcomeRepository,
    MarketRegimeRepository,
    MarketSnapshotRepository,
    PortfolioPositionRepository,
    TurnoverCapEventRepository,
)
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.live_price import fetch_live_price
from app.portfolio.schemas import PortfolioPosition, TurnoverCapEvent

router = APIRouter(prefix="/portfolio", tags=["portfolio"], dependencies=[Depends(verify_api_key)])


@router.get("/positions", response_model=list[PortfolioPosition])
def get_positions(repo: PortfolioPositionRepository = Depends(get_portfolio_position_repo)) -> list[PortfolioPosition]:
    """Raw current holdings, exactly as stored."""
    return list(repo.get_all().values())


@router.get("/turnover-cap-events/recent", response_model=list[TurnoverCapEvent])
def get_recent_turnover_cap_events(
    limit: int = 20, repo: TurnoverCapEventRepository = Depends(get_turnover_cap_event_repo),
) -> list[TurnoverCapEvent]:
    """Every real run where MAX_WEEKLY_TURNOVER capped at least one
    proposed position change, newest first -- found live 2026-09-14 as a
    completely invisible-after-the-fact stdout-only warning before this
    (see TurnoverCapEvent's own docstring). `fully_blocked=true` means
    EVERY proposed change that run was reverted, not just scaled down."""
    return repo.get_recent(limit=limit)


@router.get("/state", response_model=list[PortfolioStateEntry])
def get_portfolio_state(
    position_repo: PortfolioPositionRepository = Depends(get_portfolio_position_repo),
    asset_repo: AssetRepository = Depends(get_asset_repo),
    outcome_repo: DecisionOutcomeRepository = Depends(get_decision_outcome_repo),
    regime_repo: MarketRegimeRepository = Depends(get_regime_repo),
    snapshot_repo: MarketSnapshotRepository = Depends(get_market_snapshot_repo),
    binance_client: BinanceClient = Depends(get_binance_client),
    coinbase_client: CoinbaseClient = Depends(get_coinbase_client),
) -> list[PortfolioStateEntry]:
    """Current holdings joined with each position's most recent decision's
    tracked outcome — mark-to-mid vs. net-of-costs and `assumed_fill_method`
    surfaced explicitly per fill (Phase 4 built this specifically to make a
    previously-hidden assumption visible; this view does not hide it
    again). `outcome` is `null` when the decision hasn't resolved yet, or
    when there's no `last_decision_id` at all — an honest empty state, not
    an error. `regime_label` (Phase 5b) resolves `outcome.regime_at_decision`
    (a raw snapshot id) to its real regime string, since that FK is never
    the human-readable label itself. `price_usd`/`price_as_of` (Phase 5b)
    are this asset's last *collected* price and its snapshot timestamp —
    `live_price_usd`/`live_price_as_of`/`live_price_source` are a separate,
    genuinely live spot price fetched at request time (by explicit user
    choice, kept out of `current_allocation`'s own math — see
    `app/market_data/live_price.py`). All `None` when not available,
    never fabricated."""
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
        regime_label = None
        if outcome is not None and outcome.regime_at_decision:
            snapshot = regime_repo.get_by_id(outcome.regime_at_decision)
            regime_label = snapshot.regime if snapshot is not None else None
        price_snapshot = snapshot_repo.get_latest_snapshot(asset_id)
        price_usd = float(price_snapshot.price) if price_snapshot is not None else None
        price_as_of = price_snapshot.timestamp if price_snapshot is not None else None
        live = fetch_live_price(asset.symbol, binance_client, coinbase_client)
        entries.append(PortfolioStateEntry(
            asset_id=asset_id, symbol=asset.symbol, current_allocation=position.current_allocation,
            last_decision_id=position.last_decision_id, updated_at=position.updated_at, outcome=outcome,
            regime_label=regime_label, price_usd=price_usd, price_as_of=price_as_of,
            live_price_usd=live.price if live else None,
            live_price_as_of=live.as_of if live else None,
            live_price_source=live.source if live else None,
        ))
    return entries
