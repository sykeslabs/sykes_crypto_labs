from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import get_adversarial_repo, get_assessment_repo
from app.database.repository import AdversarialResearchRepository, ModelMarketAssessmentRepository
from app.llm.adversarial_schemas import AdversarialResearchRecord
from app.llm.assessment_schemas import ModelMarketAssessmentRecord

router = APIRouter(prefix="/assessments", tags=["assessments"], dependencies=[Depends(verify_api_key)])


@router.get("/latest", response_model=list[ModelMarketAssessmentRecord])
def get_latest_assessments(
    repo: ModelMarketAssessmentRepository = Depends(get_assessment_repo),
) -> list[ModelMarketAssessmentRecord]:
    """3d's independent multi-model assessments from the most recent
    assessment run, across every candidate and every model — includes
    `model_agreement` per (run, asset)."""
    return repo.get_latest_run_assessments()


@router.get("/asset/{asset_id}", response_model=list[ModelMarketAssessmentRecord])
def get_assessments_for_asset(
    asset_id: str, limit: int = 10, repo: ModelMarketAssessmentRepository = Depends(get_assessment_repo),
) -> list[ModelMarketAssessmentRecord]:
    return repo.get_latest_by_asset(asset_id, limit=limit)


@router.get("/adversarial/recent", response_model=list[AdversarialResearchRecord])
def get_recent_adversarial_research(
    limit: int = 50, repo: AdversarialResearchRepository = Depends(get_adversarial_repo),
) -> list[AdversarialResearchRecord]:
    """3f's bull/bear/scenario research, newest first."""
    return repo.get_recent(limit=limit)


@router.get("/adversarial/asset/{asset_id}", response_model=AdversarialResearchRecord | None)
def get_adversarial_research_for_asset(
    asset_id: str, repo: AdversarialResearchRepository = Depends(get_adversarial_repo),
) -> AdversarialResearchRecord | None:
    return repo.get_latest_by_asset(asset_id)
