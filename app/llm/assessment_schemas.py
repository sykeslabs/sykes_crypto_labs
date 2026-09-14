from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["BULLISH", "NEUTRAL", "BEARISH"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class Horizon(BaseModel):
    short_term_days: int
    medium_term_days: int
    long_term_days: int


class DirectionSet(BaseModel):
    short_term: Direction
    medium_term: Direction
    long_term: Direction


class ConfidenceSet(BaseModel):
    short_term: float = Field(ge=0.0, le=1.0)
    medium_term: float = Field(ge=0.0, le=1.0)
    long_term: float = Field(ge=0.0, le=1.0)


class ExpectedReturn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    return_7d: float = Field(alias="7d")
    return_30d: float = Field(alias="30d")
    return_90d: float = Field(alias="90d")


class RiskAssessment(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    level: RiskLevel


class WeightedFactor(BaseModel):
    """One entry in key_drivers/key_risks — a labeled factor with the
    model's own read of its direction and importance, not a collector-level
    signal (matches the "no editorializing at the collector level" rule
    used throughout 3b/3c; this is the model's own reasoning, not ours)."""

    factor: str
    direction: Direction
    importance: float = Field(ge=0.0, le=1.0)
    reason: str


class SourceAssessmentEntry(BaseModel):
    """The model's own read of one evidence source's stance — e.g. how it
    weighed 3c's Binance funding rate or 3b's composite_factor_score. Only
    sources genuinely present in the prompt context may appear here (see
    the 3d non-negotiable)."""

    source: str
    direction: Direction
    importance: float = Field(ge=0.0, le=1.0)
    reason: str


class AssetAssessment(BaseModel):
    """One model's structured current-market assessment for one asset."""

    asset: str
    assessment_timestamp: datetime
    horizon: Horizon
    direction: DirectionSet
    confidence: ConfidenceSet
    expected_return: ExpectedReturn
    risk: RiskAssessment
    market_regime: str
    key_drivers: list[WeightedFactor] = []
    key_risks: list[WeightedFactor] = []
    source_assessment: list[SourceAssessmentEntry] = []
    thesis: str
    invalidation_conditions: list[str] = []
    overall_assessment: Direction


class AssessmentBatch(BaseModel):
    """One provider's response for every TOP_CANDIDATE in a single call —
    same batched-call-per-provider pattern as Phase 2's AnalysisBatch."""

    assessments: list[AssetAssessment]


class ModelMarketAssessmentRecord(BaseModel):
    """One (provider, asset) assessment as persisted in
    `model_market_assessments`."""

    id: str | None = None
    run_id: str
    asset_id: str
    provider: str
    model: str
    prompt_template_id: str | None
    assessment_timestamp: datetime
    data_cutoff_timestamp: datetime
    short_term_direction: Direction
    medium_term_direction: Direction
    long_term_direction: Direction
    short_term_confidence: float
    medium_term_confidence: float
    long_term_confidence: float
    expected_return_7d: float
    expected_return_30d: float
    expected_return_90d: float
    risk_score: float
    risk_level: RiskLevel
    market_regime: str
    model_agreement: float
    # Additive continuous complement to model_agreement's coarse discrete
    # majority-vote fraction -- see compute_return_dispersion's own
    # docstring. None when only one model's response was usable (nothing to
    # compute a spread from), never fabricated as 0.
    expected_return_dispersion_30d: float | None = None
    overall_assessment: Direction
    thesis: str
    key_drivers: list[dict]
    key_risks: list[dict]
    source_assessment: list[dict]
    invalidation_conditions: list[str]
    raw_response: dict | None
    estimated_cost: Decimal

    def to_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "asset_id": self.asset_id,
            "provider": self.provider,
            "model": self.model,
            "prompt_template_id": self.prompt_template_id,
            "assessment_timestamp": self.assessment_timestamp.isoformat(),
            "data_cutoff_timestamp": self.data_cutoff_timestamp.isoformat(),
            "short_term_direction": self.short_term_direction,
            "medium_term_direction": self.medium_term_direction,
            "long_term_direction": self.long_term_direction,
            "short_term_confidence": self.short_term_confidence,
            "medium_term_confidence": self.medium_term_confidence,
            "long_term_confidence": self.long_term_confidence,
            "expected_return_7d": self.expected_return_7d,
            "expected_return_30d": self.expected_return_30d,
            "expected_return_90d": self.expected_return_90d,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "market_regime": self.market_regime,
            "model_agreement": self.model_agreement,
            "expected_return_dispersion_30d": self.expected_return_dispersion_30d,
            "overall_assessment": self.overall_assessment,
            "thesis": self.thesis,
            "key_drivers": self.key_drivers,
            "key_risks": self.key_risks,
            "source_assessment": self.source_assessment,
            "invalidation_conditions": self.invalidation_conditions,
            "raw_response": self.raw_response,
            "estimated_cost": str(self.estimated_cost),
        }
