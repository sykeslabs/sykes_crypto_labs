from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import verify_api_key
from app.api.dependencies import get_judge_decision_repo, get_reasoning_audit_repo
from app.database.repository import JudgeDecisionRepository, JudgeReasoningAuditRepository
from app.benchmarks.schemas import JudgeReasoningAuditRecord
from app.judge.schemas import JudgeDecisionRecord

router = APIRouter(prefix="/judge", tags=["judge"], dependencies=[Depends(verify_api_key)])


@router.get("/decisions/recent", response_model=list[JudgeDecisionRecord])
def get_recent_decisions(
    limit: int = 50, is_backfilled: bool | None = None,
    repo: JudgeDecisionRepository = Depends(get_judge_decision_repo),
) -> list[JudgeDecisionRecord]:
    """3e's full decision records (thesis, key/contradictory evidence,
    invalidation conditions), newest first. `is_backfilled` optionally
    filters to just backfilled or just live decisions — never mixed
    silently, per 3e.1's own non-negotiable."""
    return repo.get_recent(limit=limit, is_backfilled=is_backfilled)


@router.get("/decisions/{decision_id}", response_model=JudgeDecisionRecord)
def get_decision(decision_id: str, repo: JudgeDecisionRepository = Depends(get_judge_decision_repo)) -> JudgeDecisionRecord:
    record = repo.get_by_id(decision_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    return record


@router.get("/decisions/asset/{asset_id}/latest", response_model=JudgeDecisionRecord | None)
def get_latest_decision_for_asset(
    asset_id: str, repo: JudgeDecisionRepository = Depends(get_judge_decision_repo),
) -> JudgeDecisionRecord | None:
    return repo.get_latest_by_asset(asset_id)


@router.get("/reasoning-audits/recent", response_model=list[JudgeReasoningAuditRecord])
def get_recent_reasoning_audits(
    limit: int = 50, repo: JudgeReasoningAuditRepository = Depends(get_reasoning_audit_repo),
) -> list[JudgeReasoningAuditRecord]:
    """3g's formalized reasoning audits — whether a decision's thesis
    actually follows from its own cited evidence."""
    return repo.get_recent(limit=limit)


@router.get("/reasoning-audits/decision/{decision_id}", response_model=list[JudgeReasoningAuditRecord])
def get_reasoning_audits_for_decision(
    decision_id: str, repo: JudgeReasoningAuditRepository = Depends(get_reasoning_audit_repo),
) -> list[JudgeReasoningAuditRecord]:
    return repo.get_by_decision_id(decision_id)
