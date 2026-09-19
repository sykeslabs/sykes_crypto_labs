"""A generic structured-JSON-output OpenRouter caller, parameterized by the
expected Pydantic response model at call time.

Unlike Phase 2/3d/3e's provider classes (`OpenRouterProvider`,
`OpenRouterAssessmentProvider`, `OpenRouterJudgeProvider` — each hardcoded
to one batch-response type and deliberately kept separate to avoid touching
an already-shipped, live-verified class), this one has no existing call
sites to risk regressing: 3f's bull/bear/scenario stages are three
DIFFERENT schemas in the same research cycle, and writing three near-
identical hardcoded classes for genuinely new code would be pure
duplication with no corresponding safety benefit. A real generalization,
not a shortcut.
"""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.cost import compute_cost
from app.llm.schemas import TokenUsage

logger = logging.getLogger("crypto_ai_portfolio.llm")

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

T = TypeVar("T", bound=BaseModel)


@dataclass
class StructuredCallResult:
    provider: str
    model: str
    parsed: BaseModel | None
    token_usage: TokenUsage | None
    estimated_cost: Decimal
    raw_response: dict | None
    error: str | None


class OpenRouterStructuredProvider:
    """Same retry-once-on-invalid-JSON pattern as every other OpenRouter
    provider in this codebase, generalized over the response schema."""

    def __init__(
        self,
        name: str,
        model: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        extra_request_params: dict | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout_seconds
        # See app/llm/openrouter_client.py's OpenRouterProvider for the real
        # 2026-09-18 incident this exists for -- optional, no change in
        # behavior for any caller that doesn't pass it.
        self._extra_request_params = extra_request_params or {}

    def call(self, system_prompt: str, user_prompt: str, response_model: type[T]) -> StructuredCallResult:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        first = self._attempt(messages, response_model)
        if first.error is None:
            return first

        logger.warning(
            "%s (%s) returned invalid structured output, retrying once: %s",
            self.name, self.model, first.error,
        )

        retry_messages = messages + [
            {"role": "assistant", "content": _extract_content(first.raw_response)},
            {
                "role": "user",
                "content": (
                    "That response was not valid JSON matching the required schema. "
                    "Respond again with ONLY the JSON object, no other text, no markdown fences."
                ),
            },
        ]
        second = self._attempt(retry_messages, response_model)

        combined_cost = first.estimated_cost + second.estimated_cost
        combined_tokens = _sum_tokens(first.token_usage, second.token_usage)

        if second.error is not None:
            logger.error(
                "%s (%s) failed structured output validation twice: %s",
                self.name, self.model, second.error,
            )

        return StructuredCallResult(
            provider=self.name, model=self.model, parsed=second.parsed,
            token_usage=combined_tokens, estimated_cost=combined_cost,
            raw_response=second.raw_response, error=second.error,
        )

    def _attempt(self, messages: list[dict], response_model: type[T]) -> StructuredCallResult:
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "messages": messages, "temperature": 0.4, **self._extra_request_params},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return StructuredCallResult(
                provider=self.name, model=self.model, parsed=None, token_usage=None,
                estimated_cost=Decimal("0"), raw_response=None, error=f"Request failed: {exc}",
            )

        # Real incident 2026-09-18: OpenRouter can return HTTP 200 with an
        # `{"error": ...}` envelope instead of a real completion (e.g. the
        # underlying provider rate-limited/filtered/errored) -- previously
        # this was silently discarded by _extract_content's blanket except,
        # surfacing only a misleading "Expecting value: line 1 column 1"
        # JSON-decode error with no way to tell a genuine empty completion
        # apart from a real, informative upstream error. Checked and logged
        # explicitly now, before any content extraction is attempted.
        if isinstance(data, dict) and "error" in data:
            logger.error(
                "%s (%s) provider error in response body: %s", self.name, self.model, data["error"],
            )
            return StructuredCallResult(
                provider=self.name, model=self.model, parsed=None, token_usage=None,
                estimated_cost=Decimal("0"), raw_response=data, error=f"Provider error: {data['error']}",
            )

        usage = data.get("usage") or {}
        token_usage = TokenUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        cost = compute_cost(self.model, token_usage.prompt_tokens, token_usage.completion_tokens)

        # Real incident 2026-09-18 (Gemini 2.5 Pro): a per-CHOICE error, not
        # a top-level one -- see OpenRouterProvider's own comment for the
        # full incident. Real tokens were genuinely billed, so cost/
        # token_usage from above are kept here, unlike the request-level
        # failure branch above which has none to report.
        choices = data.get("choices") or []
        choice_error = choices[0].get("error") if choices and isinstance(choices[0], dict) else None
        if choice_error is not None:
            logger.error(
                "%s (%s) per-choice provider error: %s", self.name, self.model, choice_error,
            )
            return StructuredCallResult(
                provider=self.name, model=self.model, parsed=None, token_usage=token_usage,
                estimated_cost=cost, raw_response=data, error=f"Provider error: {choice_error}",
            )

        content = _extract_content(data)
        try:
            parsed_json = json.loads(_JSON_FENCE_RE.sub("", content).strip())
            parsed = response_model.model_validate(parsed_json)
        except (json.JSONDecodeError, ValidationError) as exc:
            # Full raw response logged here (not just the exception string)
            # so a genuinely-empty-completion failure is actually
            # diagnosable after the fact -- previously only the parse
            # exception text was ever logged, the response body itself was
            # never captured anywhere.
            logger.error(
                "%s (%s) raw response body on parse failure: %s", self.name, self.model, data,
            )
            return StructuredCallResult(
                provider=self.name, model=self.model, parsed=None, token_usage=token_usage,
                estimated_cost=cost, raw_response=data, error=f"Invalid structured output: {exc}",
            )

        return StructuredCallResult(
            provider=self.name, model=self.model, parsed=parsed, token_usage=token_usage,
            estimated_cost=cost, raw_response=data, error=None,
        )


def _extract_content(raw_response: dict | None) -> str:
    if not raw_response:
        return ""
    try:
        return raw_response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _sum_tokens(a: TokenUsage | None, b: TokenUsage | None) -> TokenUsage | None:
    if a is None and b is None:
        return None
    a = a or TokenUsage(prompt_tokens=0, completion_tokens=0)
    b = b or TokenUsage(prompt_tokens=0, completion_tokens=0)
    return TokenUsage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
    )
