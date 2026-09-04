from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Action = Literal["BUY", "HOLD", "SELL"]


class InvestmentAnalysis(BaseModel):
    """One model's structured opinion on one asset.

    `target_allocation` is a fraction of total portfolio value (0.0-1.0), not
    a percentage — kept consistent with `confidence` and with the Risk
    Engine's max-single-asset-allocation rule (Phase 3).
    """

    asset_symbol: str
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    target_allocation: float = Field(ge=0.0, le=1.0)
    investment_horizon: str
    thesis: str
    bull_case: str
    bear_case: str
    catalysts: list[str] = []
    risks: list[str] = []
    invalidation_conditions: list[str] = []


class AnalysisBatch(BaseModel):
    """One provider's response for the whole asset universe in a single call."""

    analyses: list[InvestmentAnalysis]


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class LLMAnalysisRecord(BaseModel):
    """One (provider, asset) analysis as persisted in `llm_analyses`."""

    id: str | None = None
    run_id: str
    asset_id: str
    provider: str
    model: str
    prompt_version: str
    timestamp: datetime
    input_hash: str
    response: dict
    action: Action
    confidence: float
    target_allocation: float
    investment_horizon: str
    bull_case: str
    bear_case: str
    catalysts: list[str]
    risks: list[str]
    invalidation_conditions: list[str]
    token_usage: TokenUsage | None
    estimated_cost: Decimal

    def to_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "asset_id": self.asset_id,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "timestamp": self.timestamp.isoformat(),
            "input_hash": self.input_hash,
            "response": self.response,
            "action": self.action,
            "confidence": self.confidence,
            "target_allocation": self.target_allocation,
            "investment_horizon": self.investment_horizon,
            "bull_case": self.bull_case,
            "bear_case": self.bear_case,
            "catalysts": self.catalysts,
            "risks": self.risks,
            "invalidation_conditions": self.invalidation_conditions,
            "token_usage": self.token_usage.model_dump() if self.token_usage else None,
            "estimated_cost": str(self.estimated_cost),
        }
