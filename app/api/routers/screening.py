from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import verify_api_key
from app.api.dependencies import (
    get_asset_repo,
    get_binance_client,
    get_coinbase_client,
    get_coingecko_client,
    get_regime_repo,
    get_screened_universe_repo,
)
from app.api.schemas import LiveFactorSnapshot
from app.database.models import Asset
from app.database.repository import AssetRepository, MarketRegimeRepository, ScreenedUniverseRepository
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.coingecko import CoinGeckoClient
from app.market_data.factors import compute_max_drawdown, compute_relative_strength, compute_volatility
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset

router = APIRouter(prefix="/screening", tags=["screening"], dependencies=[Depends(verify_api_key)])

# Same 31-day lookback screening itself uses (app/market_data/screening_service.py's
# OHLCV_LOOKBACK_DAYS) -- kept identical so a live volatility/drawdown
# recompute is genuinely comparable to the stored figure, not an
# apples-to-oranges window.
LIVE_FACTOR_OHLCV_LOOKBACK_DAYS = 31


@router.get("/universe", response_model=list[ScreenedAsset])
def get_universe(repo: ScreenedUniverseRepository = Depends(get_screened_universe_repo)) -> list[ScreenedAsset]:
    """Layer 1 (widest) of asset discovery: every screened asset from the
    most recent run — the top `SCREENING_UNIVERSE_SIZE` (default 30) by
    CoinGecko market cap, stablecoins excluded — not just TOP_CANDIDATES.
    For checking survivorship bias in discovery."""
    return repo.get_latest_full_universe()


@router.get("/candidates", response_model=list[ScreenedAsset])
def get_candidates(repo: ScreenedUniverseRepository = Depends(get_screened_universe_repo)) -> list[ScreenedAsset]:
    """Layer 2 (middle) of asset discovery: 3b's latest TOP_CANDIDATES —
    the top `TOP_CANDIDATES_SIZE` (default 10) of Layer 1's universe by
    composite factor score. Empty list if `--with-screening` has never
    been run — an honest empty state, not an error."""
    return repo.get_latest_top_candidates()


@router.get("/tracked", response_model=list[Asset])
def get_tracked_assets(repo: AssetRepository = Depends(get_asset_repo)) -> list[Asset]:
    """Layer 3 (narrowest) of asset discovery: every currently-tracked
    asset (`assets.active`) — accumulated over every screening run's
    Layer-2 promotions (`ScreeningService._promote_new_candidates`) plus
    Phase 1's manually-seeded initial set, never automatically demoted.
    This is the actual set everything downstream (news matching, Judge
    decisions, holdings symbol lookup) operates on — not Layer 1 or 2
    directly. Sorted by symbol for a stable, readable list."""
    return sorted(repo.get_active_assets(), key=lambda a: a.symbol)


@router.get("/live-factors/{symbol}", response_model=LiveFactorSnapshot)
def get_live_factors(
    symbol: str,
    screened_universe_repo: ScreenedUniverseRepository = Depends(get_screened_universe_repo),
    coingecko_client: CoinGeckoClient = Depends(get_coingecko_client),
    binance_client: BinanceClient = Depends(get_binance_client),
    coinbase_client: CoinbaseClient = Depends(get_coinbase_client),
) -> LiveFactorSnapshot:
    """A genuinely live, on-demand recomputation of `symbol`'s six
    screening factors, using the same pure functions
    (`app/market_data/factors.py`) and the same Binance-primary/
    Coinbase-fallback OHLCV source selection real screening runs use —
    display-only (see `LiveFactorSnapshot`'s own docstring for why this
    never feeds any real computation). Looked up by `symbol` against the
    most recent screening run to get a real `coingecko_id` (works for any
    symbol ever screened, not just currently-tracked assets) — 404 if this
    symbol was never screened at all, since there's no real id to fetch
    live data for."""
    screened = screened_universe_repo.get_latest_for_symbol(symbol)
    if screened is None or not screened.coingecko_id:
        raise HTTPException(status_code=404, detail=f"'{symbol}' has no real coingecko_id on record from any screening run.")

    markets = coingecko_client.fetch_markets([screened.coingecko_id, "bitcoin"])
    asset_market = markets.get(screened.coingecko_id)
    btc_market = markets.get("bitcoin")
    momentum_30d = asset_market.get("price_change_percentage_30d_in_currency") if asset_market else None
    momentum_7d = asset_market.get("price_change_percentage_7d_in_currency") if asset_market else None
    btc_momentum_30d = btc_market.get("price_change_percentage_30d_in_currency") if btc_market else None
    volume_24h = asset_market.get("total_volume") if asset_market else None
    relative_strength_30d = compute_relative_strength(momentum_30d, btc_momentum_30d)

    closes: list[float] = []
    ohlcv_source = "UNAVAILABLE"
    try:
        rows = binance_client.fetch_daily_ohlcv(symbol, LIVE_FACTOR_OHLCV_LOOKBACK_DAYS)
        if rows:
            closes = [c for c, _v in rows]
            ohlcv_source = "BINANCE"
    except Exception:
        pass
    if not closes:
        try:
            rows = coinbase_client.fetch_daily_ohlcv(symbol, LIVE_FACTOR_OHLCV_LOOKBACK_DAYS)
            if rows:
                closes = [c for c, _v in rows]
                ohlcv_source = "COINBASE"
        except Exception:
            pass

    return LiveFactorSnapshot(
        symbol=symbol,
        momentum_7d=momentum_7d,
        momentum_30d=momentum_30d,
        relative_strength_30d=relative_strength_30d,
        volatility_30d=compute_volatility(closes) if closes else None,
        drawdown_30d=compute_max_drawdown(closes) if closes else None,
        volume_24h=volume_24h,
        volatility_drawdown_source=ohlcv_source,
        computed_at=datetime.now(UTC),
    )


@router.get("/regime", response_model=MarketRegimeSnapshot | None)
def get_regime(repo: MarketRegimeRepository = Depends(get_regime_repo)) -> MarketRegimeSnapshot | None:
    """The shared market-regime snapshot every downstream stage (3d, 3e)
    reads. None if never computed."""
    return repo.get_latest()
