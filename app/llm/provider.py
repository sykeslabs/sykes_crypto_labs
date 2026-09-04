from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.llm.schemas import AnalysisBatch, TokenUsage


@dataclass
class ProviderResult:
    provider: str
    model: str
    batch: AnalysisBatch | None
    token_usage: TokenUsage | None
    estimated_cost: Decimal
    raw_response: dict | None
    error: str | None


class LLMProvider(Protocol):
    """Abstraction the rest of the app depends on — not OpenRouter-specific,
    so swapping to a direct Anthropic/OpenAI/Google connection later doesn't
    require touching callers."""

    name: str
    model: str

    def analyze(self, system_prompt: str, user_prompt: str) -> ProviderResult: ...
