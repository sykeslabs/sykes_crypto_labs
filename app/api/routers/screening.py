from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import get_regime_repo, get_screened_universe_repo
from app.database.repository import MarketRegimeRepository, ScreenedUniverseRepository
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset

router = APIRouter(prefix="/screening", tags=["screening"], dependencies=[Depends(verify_api_key)])


@router.get("/candidates", response_model=list[ScreenedAsset])
def get_candidates(repo: ScreenedUniverseRepository = Depends(get_screened_universe_repo)) -> list[ScreenedAsset]:
    """3b's latest TOP_CANDIDATES. Empty list if `--with-screening` has
    never been run — an honest empty state, not an error."""
    return repo.get_latest_top_candidates()


@router.get("/universe", response_model=list[ScreenedAsset])
def get_universe(repo: ScreenedUniverseRepository = Depends(get_screened_universe_repo)) -> list[ScreenedAsset]:
    """Every screened asset from the most recent run, not just
    TOP_CANDIDATES — for checking survivorship bias in discovery."""
    return repo.get_latest_full_universe()


@router.get("/regime", response_model=MarketRegimeSnapshot | None)
def get_regime(repo: MarketRegimeRepository = Depends(get_regime_repo)) -> MarketRegimeSnapshot | None:
    """The shared market-regime snapshot every downstream stage (3d, 3e)
    reads. None if never computed."""
    return repo.get_latest()
