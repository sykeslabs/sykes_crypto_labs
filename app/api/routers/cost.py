from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import get_cost_ledger_repo, get_settings_dependency
from app.api.schemas import CostSummary, CostTableBreakdown, CostWindowReport
from app.config import Settings
from app.llm.cost import CostLedgerRepository

router = APIRouter(prefix="/cost", tags=["cost"], dependencies=[Depends(verify_api_key)])


def _window_report(repo: CostLedgerRepository, since: datetime, cap: Decimal) -> CostWindowReport:
    by_table = repo.get_cost_sum_by_table_since(since)
    total = sum(by_table.values(), Decimal("0"))
    remaining = max(cap - total, Decimal("0"))
    return CostWindowReport(
        since=since,
        total_usd=str(total),
        cap_usd=str(cap),
        remaining_usd=str(remaining),
        by_table=[CostTableBreakdown(table=t, cost_usd=str(c)) for t, c in by_table.items()],
    )


@router.get("/summary", response_model=CostSummary)
def get_cost_summary(
    repo: CostLedgerRepository = Depends(get_cost_ledger_repo),
    settings: Settings = Depends(get_settings_dependency),
) -> CostSummary:
    """`COST_TRACKED_TABLES` sums by table, for today and this month,
    against the configured `MAX_DAILY_LLM_COST`/`MAX_MONTHLY_LLM_COST`
    caps. This is the app's own tracked ledger, NOT a live provider-billing
    balance -- this project has twice had a real gap between the two
    (3e.1's CostGuard blind spot, the OpenRouter account-vs-key-limit
    confusion in 3f), so the two are never implied to match."""
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    return CostSummary(
        daily=_window_report(repo, day_start, settings.max_daily_llm_cost),
        monthly=_window_report(repo, month_start, settings.max_monthly_llm_cost),
    )
