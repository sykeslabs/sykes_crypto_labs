from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.judge.decisions import DecisionValue

RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class JudgeDecisionItem(BaseModel):
    """One Judge decision for one asset, as returned by the LLM. Kept as
    plain strings for key_evidence/contradictory_evidence/key_risks/
    invalidation_conditions — PHASE3E_PROMPT.md's own example shows these as
    empty arrays with no nested shape, unlike 3d's structured key_drivers/
    key_risks; inventing structure beyond what's specified isn't warranted.
    """

    asset: str
    decision: DecisionValue
    confidence: float = Field(ge=0.0, le=1.0)
    # The Judge's UNCONSTRAINED view — Risk Engine/Portfolio Construction
    # finalize actual sizing, never take this verbatim (per task 1's own note).
    target_allocation: float = Field(ge=0.0, le=1.0)
    expected_return: float
    expected_alpha: float
    risk_score: float = Field(ge=0.0, le=1.0)
    # The Judge's own stated uncertainty — explicitly NOT derived from, and
    # never averaged with, model_agreement/source_agreement below (both are
    # independent inputs the Judge reasons about, not blended into this).
    uncertainty: float = Field(ge=0.0, le=1.0)
    model_agreement: float = Field(ge=0.0, le=1.0)
    source_agreement: float = Field(ge=0.0, le=1.0)
    investment_horizon_days: int
    key_evidence: list[str] = []
    contradictory_evidence: list[str] = []
    key_risks: list[str] = []
    invalidation_conditions: list[str] = []
    requires_review: bool = False
    thesis: str


class JudgeDecisionBatch(BaseModel):
    """One Judge call's response for every candidate asset in the run —
    same batched-call-per-run pattern as Phase 2/3d (one structured
    request/response, not one call per asset)."""

    decisions: list[JudgeDecisionItem]


class JudgeDecisionRecord(BaseModel):
    """One asset's decision as persisted in `judge_decisions` (3a schema)."""

    id: str | None = None
    run_id: str
    asset_id: str
    created_at: datetime
    decision: DecisionValue
    confidence: float
    target_allocation: float
    expected_return: float
    expected_alpha: float
    risk_score: float
    uncertainty: float
    model_agreement: float
    source_agreement: float
    investment_horizon_days: int
    key_evidence: list[str]
    contradictory_evidence: list[str]
    key_risks: list[str]
    invalidation_conditions: list[str]
    requires_review: bool
    thesis: str
    regime_id: str | None
    prompt_template_id: str | None
    estimated_cost: Decimal

    def to_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "asset_id": self.asset_id,
            "created_at": self.created_at.isoformat(),
            "decision": self.decision,
            "confidence": self.confidence,
            "target_allocation": self.target_allocation,
            "expected_return": self.expected_return,
            "expected_alpha": self.expected_alpha,
            "risk_score": self.risk_score,
            "uncertainty": self.uncertainty,
            "model_agreement": self.model_agreement,
            "source_agreement": self.source_agreement,
            "investment_horizon_days": self.investment_horizon_days,
            "key_evidence": self.key_evidence,
            "contradictory_evidence": self.contradictory_evidence,
            "key_risks": self.key_risks,
            "invalidation_conditions": self.invalidation_conditions,
            "requires_review": self.requires_review,
            "thesis": self.thesis,
            "regime_id": self.regime_id,
            "prompt_template_id": self.prompt_template_id,
            "estimated_cost": str(self.estimated_cost),
        }
