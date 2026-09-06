from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class BullCase(BaseModel):
    """One asset's strongest evidence-based bull thesis (task 3)."""

    asset: str
    thesis: str
    catalysts: list[str] = []
    evidence: list[str] = []


class BullBatch(BaseModel):
    cases: list[BullCase]


class BearCase(BaseModel):
    """One asset's bear case — explicitly instructed to attack the SPECIFIC
    bull thesis for that asset (task 3), not a generic list of risks.
    `attacks_bull_point` names which bull catalyst/evidence item each attack
    point rebuts, so "genuinely adversarial, not independent" is checkable,
    not just claimed."""

    asset: str
    attack_points: list[str] = []
    evidence: list[str] = []
    attacks_bull_point: list[str] = []


class BearBatch(BaseModel):
    cases: list[BearCase]


class Scenario(BaseModel):
    probability: float = Field(ge=0.0, le=1.0)
    expected_return: float
    price_target: float | None = None
    timeframe: str
    assumptions: list[str] = []
    catalysts: list[str] = []
    failure_conditions: list[str] = []


class ScenarioSet(BaseModel):
    """Bull/base/bear scenarios for one asset (task 4)."""

    asset: str
    bull: Scenario
    base: Scenario
    bear: Scenario


class ScenarioBatch(BaseModel):
    scenarios: list[ScenarioSet]


class AdversarialResearchRecord(BaseModel):
    """One asset's full research cycle as persisted in
    `adversarial_research` (task 4a) — bull + bear + scenarios from one
    shared research cycle, plus the summed cost of every LLM call that
    produced it."""

    id: str | None = None
    run_id: str
    asset_id: str
    prompt_template_id: str | None
    bull_case: dict
    bear_case: dict
    bull_rebuttal: dict | None = None
    scenarios: dict
    estimated_cost: Decimal
    created_at: datetime

    def to_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "asset_id": self.asset_id,
            "prompt_template_id": self.prompt_template_id,
            "bull_case": self.bull_case,
            "bear_case": self.bear_case,
            "bull_rebuttal": self.bull_rebuttal,
            "scenarios": self.scenarios,
            "estimated_cost": str(self.estimated_cost),
            "created_at": self.created_at.isoformat(),
        }
