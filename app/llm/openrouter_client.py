import json
import logging
import re
from decimal import Decimal

import httpx
from pydantic import ValidationError

from app.llm.cost import compute_cost
from app.llm.provider import ProviderResult
from app.llm.schemas import AnalysisBatch, TokenUsage

logger = logging.getLogger("crypto_ai_portfolio.llm")

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class OpenRouterProvider:
    """LLMProvider implementation backed by OpenRouter's chat completions API.

    Retries once, in-conversation, if the model's response isn't valid JSON
    matching AnalysisBatch — never silently accepts malformed output.
    """

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
        # Real incident 2026-09-18: Gemini 2.5 Pro entered a degenerate,
        # repetitive internal reasoning loop (~1700+ completion tokens of
        # near-duplicate "thinking" text, never reaching an actual answer)
        # and the call eventually failed with an upstream idle timeout --
        # see the per-choice error handling below. Callers can pass e.g.
        # `{"reasoning": {"max_tokens": 4096}}` to cap a specific model's
        # thinking budget via OpenRouter's unified reasoning parameter
        # (thinkingBudget for Gemini) -- optional, defaults to no change in
        # behavior for every existing caller.
        self._extra_request_params = extra_request_params or {}

    def analyze(self, system_prompt: str, user_prompt: str) -> ProviderResult:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        first = self._attempt(messages)
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
        second = self._attempt(retry_messages)

        combined_cost = first.estimated_cost + second.estimated_cost
        combined_tokens = _sum_tokens(first.token_usage, second.token_usage)

        if second.error is not None:
            logger.error(
                "%s (%s) failed structured output validation twice: %s",
                self.name, self.model, second.error,
            )

        return ProviderResult(
            provider=self.name,
            model=self.model,
            batch=second.batch,
            token_usage=combined_tokens,
            estimated_cost=combined_cost,
            raw_response=second.raw_response,
            error=second.error,
        )

    def _attempt(self, messages: list[dict]) -> ProviderResult:
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "messages": messages, "temperature": 0.3, **self._extra_request_params},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return ProviderResult(
                provider=self.name, model=self.model, batch=None, token_usage=None,
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
            return ProviderResult(
                provider=self.name, model=self.model, batch=None, token_usage=None,
                estimated_cost=Decimal("0"), raw_response=data, error=f"Provider error: {data['error']}",
            )

        usage = data.get("usage") or {}
        token_usage = TokenUsage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        cost = compute_cost(self.model, token_usage.prompt_tokens, token_usage.completion_tokens)

        # Real incident 2026-09-18 (Gemini 2.5 Pro): a per-CHOICE error, not
        # a top-level one -- `choices[0].finish_reason == "error"` with a
        # real error object (`{"code": 504, "message": "Upstream idle
        # timeout exceeded", ...}`) nested inside that choice, real usage/
        # cost still present, but `message.content` is null. The top-level
        # check above cannot catch this shape. Real tokens were genuinely
        # billed (confirmed in the raw response's own cost_details), so
        # `cost`/`token_usage` from above are kept, unlike the request-level
        # failure branches which have none to report.
        choices = data.get("choices") or []
        choice_error = choices[0].get("error") if choices and isinstance(choices[0], dict) else None
        if choice_error is not None:
            logger.error(
                "%s (%s) per-choice provider error: %s", self.name, self.model, choice_error,
            )
            return ProviderResult(
                provider=self.name, model=self.model, batch=None, token_usage=token_usage,
                estimated_cost=cost, raw_response=data, error=f"Provider error: {choice_error}",
            )

        content = _extract_content(data)
        try:
            parsed = json.loads(_JSON_FENCE_RE.sub("", content).strip())
            batch = AnalysisBatch.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            # Full raw response logged here (not just the exception string)
            # so a genuinely-empty-completion failure is actually
            # diagnosable after the fact -- previously only the parse
            # exception text was ever logged, the response body itself was
            # never captured anywhere.
            logger.error(
                "%s (%s) raw response body on parse failure: %s", self.name, self.model, data,
            )
            return ProviderResult(
                provider=self.name, model=self.model, batch=None, token_usage=token_usage,
                estimated_cost=cost, raw_response=data, error=f"Invalid structured output: {exc}",
            )

        return ProviderResult(
            provider=self.name, model=self.model, batch=batch, token_usage=token_usage,
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
