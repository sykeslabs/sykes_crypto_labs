"""Phase 3e.1: retroactive historical replay CLI entrypoint.

Runs the same model-assessment -> Judge -> Risk Engine -> Portfolio
Construction pipeline 3e already built, unmodified, against a past date
range, using only genuinely point-in-time-reconstructable evidence (see
`app/benchmarks/replay.py`'s `EVIDENCE_UNAVAILABLE_FOR_REPLAY` for exactly
what is not, and README's Phase 3e.1 section for why).

Real LLM calls are made (model-assessment + Judge, once per replayed day) —
this is real cost, gated by CostGuard the same as any other stage. Per task
4's requirement, this prints a cost estimate and requires confirmation
before running (skippable with --yes).

Usage:
    python scripts/run_replay.py --days 28
    python scripts/run_replay.py --start 2026-08-01 --end 2026-08-07
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta

from app.benchmarks.historical_factors import TRAILING_WINDOW_DAYS
from app.benchmarks.replay import (
    HistoricalReplayService,
    estimate_replay_cost,
    make_funding_rate_fetcher,
    make_historical_series_fetcher,
)
from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import (
    AssetRepository,
    AssetStatusRepository,
    DecisionOutcomeRepository,
    JudgeDecisionRepository,
    LLMAnalysisRepository,
    NewsRepository,
    PromptTemplateRepository,
    SignalSourceRepository,
)
from app.judge.provider import OpenRouterJudgeProvider
from app.llm.assessment_provider import OpenRouterAssessmentProvider
from app.llm.cost import CostGuard, CostLedgerRepository
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient


def main() -> int:
    parser = argparse.ArgumentParser(description="3e.1: retroactive historical replay")
    parser.add_argument("--days", type=int, default=28, help="Replay the past N days ending --end (default 28).")
    parser.add_argument("--start", type=str, default=None, help="Explicit start date YYYY-MM-DD (overrides --days).")
    parser.add_argument("--end", type=str, default=None, help="Explicit end date YYYY-MM-DD (default: today).")
    parser.add_argument("--yes", action="store_true", help="Skip the cost-estimate confirmation prompt.")
    args = parser.parse_args()

    settings = get_settings()
    client = get_supabase_client()

    end_date = (
        datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC) if args.end else datetime.now(UTC)
    )
    start_date = (
        datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)
        if args.start else end_date - timedelta(days=args.days - 1)
    )
    num_days = (end_date.date() - start_date.date()).days + 1

    estimated_cost = estimate_replay_cost(num_days)
    print(f"Replay window: {start_date.date()} to {end_date.date()} ({num_days} days)")
    print(f"Estimated cost: ${estimated_cost} (~$0.575/day: 3-model assessment + 1-model Judge, observed live)")
    print(f"MAX_DAILY_LLM_COST=${settings.max_daily_llm_cost}  MAX_MONTHLY_LLM_COST=${settings.max_monthly_llm_cost}")

    if not args.yes:
        confirm = input("Proceed? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return 1

    api_key_assessment, assessment_models = settings.require_assessment()
    api_key_judge, judge_model = settings.require_judge()

    binance_client = BinanceClient(settings)
    coinbase_client = CoinbaseClient(settings)
    days_needed = num_days + TRAILING_WINDOW_DAYS + 5  # buffer for the trailing lookback each factor needs

    service = HistoricalReplayService(
        settings=settings,
        asset_repo=AssetRepository(client),
        news_repo=NewsRepository(client),
        llm_analysis_repo=LLMAnalysisRepository(client),
        asset_status_repo=AssetStatusRepository(client),
        signal_source_repo=SignalSourceRepository(client),
        prompt_template_repo=PromptTemplateRepository(client),
        judge_decision_repo=JudgeDecisionRepository(client),
        decision_outcome_repo=DecisionOutcomeRepository(client),
        cost_guard=CostGuard(settings, CostLedgerRepository(client)),
        assessment_providers=[
            OpenRouterAssessmentProvider(
                name=name, model=model, api_key=api_key_assessment,
                base_url=settings.openrouter_base_url, timeout_seconds=settings.llm_request_timeout_seconds,
            )
            for name, model in assessment_models.items()
        ],
        judge_provider=OpenRouterJudgeProvider(
            name="judge", model=judge_model, api_key=api_key_judge,
            base_url=settings.openrouter_base_url, timeout_seconds=settings.llm_request_timeout_seconds,
        ),
        historical_series_fetcher=make_historical_series_fetcher(binance_client, coinbase_client, days_needed),
        funding_rate_fetcher=make_funding_rate_fetcher(binance_client),
    )

    result = service.run(start_date, end_date)
    print(result.summary)
    for day in result.days:
        print(
            f"  {day.date}: candidates={day.candidates} decisions={day.decisions_stored} "
            f"resolved_immediately={day.outcomes_resolved_immediately} cost=${day.cost} "
            f"skipped_cost_cap={day.skipped_cost_cap} error={day.error}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
