from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

OutcomeLabel = Literal["HIT_TARGET", "HIT_STOP", "TIMED_OUT", "UNRESOLVED"]


class DecisionOutcome(BaseModel):
    """One row of `decision_outcomes` (3a schema) — the continuous
    calibration ledger. `regime_at_decision`/`judge_confidence` are
    denormalized from the decision so per-regime/per-confidence-bucket
    accuracy can be reported without joining back through `judge_decisions`
    (see PHASE3E_PROMPT.md's non-negotiables)."""

    id: str | None = None
    decision_id: str
    asset_id: str
    decision_timestamp: datetime
    horizon_days: int
    target_return: float
    stop_return: float
    realized_return: float | None = None
    outcome_label: OutcomeLabel = "UNRESOLVED"
    evaluated_at: datetime | None = None
    regime_at_decision: str | None = None
    judge_confidence: float
    in_holdout_window: bool = False
    is_backfilled: bool = False

    def to_row(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "asset_id": self.asset_id,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "horizon_days": self.horizon_days,
            "target_return": self.target_return,
            "stop_return": self.stop_return,
            "realized_return": self.realized_return,
            "outcome_label": self.outcome_label,
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
            "regime_at_decision": self.regime_at_decision,
            "judge_confidence": self.judge_confidence,
            "in_holdout_window": self.in_holdout_window,
            "is_backfilled": self.is_backfilled,
        }


class CalibrationRunRecord(BaseModel):
    """One row of `calibration_runs` — a countable calibration/backtest
    *attempt*, not just a count of resolved decisions (see PHASE3E_PROMPT.md
    task 5 — this count is what 3g's deflated-Sharpe/PBO correction needs)."""

    id: str | None = None
    run_at: datetime
    method: str
    sample_size: int
    prompt_template_ids: list[str] = []
    hit_rate: float | None = None
    brier_score: float | None = None
    notes: str | None = None

    def to_row(self) -> dict:
        return {
            "run_at": self.run_at.isoformat(),
            "method": self.method,
            "sample_size": self.sample_size,
            "prompt_template_ids": self.prompt_template_ids,
            "hit_rate": self.hit_rate,
            "brier_score": self.brier_score,
            "notes": self.notes,
        }


class ReasoningAuditResult(BaseModel):
    """The LLM's structured output for one audited decision (3g task 5) —
    given only the decision's stored `thesis`/`key_evidence`/
    `contradictory_evidence`, is the thesis genuinely supported or does it
    contain an unsupported leap."""

    supported: bool
    unsupported_claims: list[str] = []
    notes: str


class JudgeReasoningAuditRecord(BaseModel):
    """One row of `judge_reasoning_audits` (3g task 5)."""

    id: str | None = None
    run_at: datetime
    decision_id: str
    audit_model: str
    supported: bool
    unsupported_claims: list[str] = []
    notes: str | None = None
    estimated_cost: Decimal
    created_at: datetime

    def to_row(self) -> dict:
        return {
            "run_at": self.run_at.isoformat(),
            "decision_id": self.decision_id,
            "audit_model": self.audit_model,
            "supported": self.supported,
            "unsupported_claims": self.unsupported_claims,
            "notes": self.notes,
            "estimated_cost": str(self.estimated_cost),
            "created_at": self.created_at.isoformat(),
        }
