from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import get_cost_ledger_repo, get_settings_dependency
from app.api.schemas import CostDayTableBreakdown, CostSummary, CostTableBreakdown, CostWindowReport
from app.config import Settings
from app.llm.cost import CostLedgerRepository

# "Since the beginning" for the /by-day endpoint's default (no `since` given)
# -- this project's "None means unlimited" convention (see /news/recent,
# /judge/decisions/recent), applied here as a fixed early epoch rather than
# a literal None so the same _window_report-style query code works
# unchanged; real data never predates this project's own existence anyway.
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)

router = APIRouter(prefix="/cost", tags=["cost"], dependencies=[Depends(verify_api_key)])


def _window_report(repo: CostLedgerRepository, since: datetime, cap: Decimal) -> CostWindowReport:
    by_table = repo.get_cost_and_count_by_table_since(since)
    total = sum((cost for cost, _count in by_table.values()), Decimal("0"))
    remaining = max(cap - total, Decimal("0"))
    return CostWindowReport(
        since=since,
        total_usd=str(total),
        cap_usd=str(cap),
        remaining_usd=str(remaining),
        by_table=[CostTableBreakdown(table=t, cost_usd=str(cost), call_count=count) for t, (cost, count) in by_table.items()],
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


@router.get("/by-day", response_model=list[CostDayTableBreakdown])
def get_cost_by_day(
    since: datetime | None = None, repo: CostLedgerRepository = Depends(get_cost_ledger_repo),
) -> list[CostDayTableBreakdown]:
    """The full day-by-day cost history behind /summary's today/this-month
    totals -- `since` omitted (default) returns every real (day, table)
    bucket ever recorded, matching /news/recent's own "None means
    unlimited" convention, since real history here never grows unbounded
    (a paper-trading pipeline run at most a few times a day)."""
    by_day_table = repo.get_cost_and_count_by_table_and_day_since(since or _EPOCH)
    return [
        CostDayTableBreakdown(date=day, table=table, cost_usd=str(cost), call_count=count)
        for (day, table), (cost, count) in sorted(by_day_table.items(), reverse=True)
    ]
