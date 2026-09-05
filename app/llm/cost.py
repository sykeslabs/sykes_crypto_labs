import logging
from datetime import UTC, datetime
from decimal import Decimal

from supabase import Client

from app.config import Settings

logger = logging.getLogger("crypto_ai_portfolio.llm")

# CostGuard-extension convention (locked pre-3a, see PHASE3_LOCKED_DECISIONS.md):
# every table that persists the result of an LLM call has an `estimated_cost`
# (numeric) column and is registered here — table name -> the timestamp
# column used to window the daily/monthly cost sum. (Tables don't share one
# timestamp column name: llm_analyses uses `timestamp`, judge_decisions (3e)
# uses `created_at` — register the actual column, don't assume.)
#
# A sub-phase that adds a new LLM-call-persisting table (3d's
# model_market_assessments, 3e's judge_decisions, 3f's bull/bear/scenario
# table, 3g's reasoning-audit table) must add it here and add a test proving
# CostGuard's cumulative sum reflects a row inserted into it — not just that
# the table exists. This is what keeps the daily/monthly cap from being
# silently under-enforced by a later sub-phase forgetting to wire in its
# cost column.
COST_TRACKED_TABLES: dict[str, str] = {
    "llm_analyses": "timestamp",
}

# $ per 1K tokens (input, output). Pulled from https://openrouter.ai/api/v1/models
# at the time this was written — OpenRouter pricing can change, so re-verify
# periodically rather than trusting this indefinitely. Unrecognized models fall
# back to DEFAULT_PRICING (a conservative estimate) so cost tracking degrades
# gracefully rather than crashing.
PRICING_PER_1K_TOKENS: dict[str, tuple[Decimal, Decimal]] = {
    "anthropic/claude-sonnet-5": (Decimal("0.002"), Decimal("0.01")),
    "anthropic/claude-opus-5": (Decimal("0.005"), Decimal("0.025")),
    "anthropic/claude-haiku-4.5": (Decimal("0.001"), Decimal("0.005")),
    "openai/gpt-5": (Decimal("0.00125"), Decimal("0.01")),
    "openai/gpt-5-mini": (Decimal("0.00025"), Decimal("0.002")),
    "openai/gpt-5-nano": (Decimal("0.00005"), Decimal("0.0004")),
    "google/gemini-2.5-pro": (Decimal("0.00125"), Decimal("0.01")),
    "google/gemini-3.1-pro-preview": (Decimal("0.002"), Decimal("0.012")),
    "google/gemini-3.5-flash": (Decimal("0.0015"), Decimal("0.009")),
}
DEFAULT_PRICING = (Decimal("0.005"), Decimal("0.015"))


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    input_price, output_price = PRICING_PER_1K_TOKENS.get(model, DEFAULT_PRICING)
    if model not in PRICING_PER_1K_TOKENS:
        logger.warning("No known pricing for model '%s' — using a conservative default estimate.", model)
    cost = (Decimal(prompt_tokens) / 1000 * input_price) + (
        Decimal(completion_tokens) / 1000 * output_price
    )
    return cost.quantize(Decimal("0.000001"))


class CostLedgerRepository:
    """Sums `estimated_cost` across every table in COST_TRACKED_TABLES —
    the single place CostGuard's cap check actually reads from."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_cost_sum_since(self, since: datetime) -> Decimal:
        total = Decimal("0")
        for table, timestamp_column in COST_TRACKED_TABLES.items():
            response = (
                self._client.table(table)
                .select("estimated_cost")
                .gte(timestamp_column, since.isoformat())
                .execute()
            )
            total += sum(
                (
                    Decimal(str(row["estimated_cost"]))
                    for row in response.data
                    if row["estimated_cost"] is not None
                ),
                Decimal("0"),
            )
        return total


class CostGuard:
    """Enforces MAX_DAILY_LLM_COST / MAX_MONTHLY_LLM_COST before each LLM call."""

    def __init__(self, settings: Settings, cost_ledger: CostLedgerRepository) -> None:
        self._settings = settings
        self._cost_ledger = cost_ledger

    def check(self) -> tuple[bool, str | None]:
        """Returns (allowed, reason). If not allowed, reason explains why."""
        now = datetime.now(UTC)

        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_spend = self._cost_ledger.get_cost_sum_since(day_start)
        if daily_spend >= self._settings.max_daily_llm_cost:
            return False, (
                f"Daily LLM cost cap reached: ${daily_spend} >= "
                f"${self._settings.max_daily_llm_cost}"
            )

        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_spend = self._cost_ledger.get_cost_sum_since(month_start)
        if monthly_spend >= self._settings.max_monthly_llm_cost:
            return False, (
                f"Monthly LLM cost cap reached: ${monthly_spend} >= "
                f"${self._settings.max_monthly_llm_cost}"
            )

        return True, None
