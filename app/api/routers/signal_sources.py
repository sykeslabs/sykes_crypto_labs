from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import get_signal_source_repo
from app.database.models import SignalSource
from app.database.repository import SignalSourceRepository

router = APIRouter(prefix="/signal-sources", tags=["signal-sources"], dependencies=[Depends(verify_api_key)])


@router.get("", response_model=list[SignalSource])
def get_signal_sources(repo: SignalSourceRepository = Depends(get_signal_source_repo)) -> list[SignalSource]:
    """Every source's real status (`OK`/`UNAVAILABLE`/`NOT_IMPLEMENTED`) and
    notes, exactly as stored -- this project has a real, hard-won history
    of sources silently going stale (3c) or being wrongly assumed
    available; this endpoint makes current status trivially checkable
    without a manual query."""
    return repo.get_all()
