import argparse
import sys
from datetime import UTC, datetime, timedelta

from app.benchmarks.evaluation_service import OutcomeEvaluationService
from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import (
    AdversarialResearchRepository,
    AssetRepository,
    AssetStatusRepository,
    DecisionOutcomeRepository,
    EvidenceObservationRepository,
    HoldingsLedgerRepository,
    JudgeDecisionRepository,
    LLMAnalysisRepository,
    MarketRegimeRepository,
    MarketSnapshotRepository,
    ModelMarketAssessmentRepository,
    NewsRepository,
    PortfolioAllocationChangeRepository,
    PortfolioPositionRepository,
    PromptTemplateRepository,
    ScreenedUniverseRepository,
    SignalSourceRepository,
)
from app.judge.provider import OpenRouterJudgeProvider
from app.judge.service import JudgeService
from app.llm.adversarial_service import AdversarialService
from app.llm.assessment_provider import OpenRouterAssessmentProvider
from app.llm.assessment_service import AssessmentService
from app.llm.cost import CostGuard, CostLedgerRepository
from app.llm.openrouter_client import OpenRouterProvider
from app.llm.service import LLMResearchService
from app.llm.structured_provider import OpenRouterStructuredProvider
from app.logging_config import new_run_id, setup_logging
from app.market_data.binance import BinanceClient
from app.market_data.cftc import CftcClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.coingecko import CoinGeckoClient
from app.market_data.coinmarketcap import CoinMarketCapClient
from app.market_data.congress_gov import CongressGovClient
from app.market_data.defillama import DefiLlamaClient
from app.market_data.deribit import DeribitClient
from app.market_data.asset_intelligence_service import AssetIntelligenceService
from app.market_data.derivatives_service import DerivativesService
from app.market_data.etherscan import EtherscanClient
from app.market_data.fred import FredClient
from app.market_data.github_activity import GitHubClient
from app.market_data.glassnode import GlassnodeClient
from app.market_data.macro_service import MacroService
from app.market_data.nansen import NansenClient
from app.market_data.screening_service import ScreeningService
from app.market_data.sec_edgar import SecEdgarClient
from app.market_data.service import MarketDataCollectionService
from app.market_data.upbit import UpbitClient
from app.news.rss_client import RssClient
from app.news.service import NewsCollectionService
from app.portfolio.construction import PortfolioConstructionService
from app.portfolio.holdings import compute_current_allocations
from app.risk.correlation import compute_daily_returns
from app.risk.engine import RiskEngine


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crypto AI Portfolio pipeline runner")
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Also collect news and run multi-model LLM research after market data collection.",
    )
    parser.add_argument(
        "--with-screening",
        action="store_true",
        help=(
            "Also run 3b's screening + market-regime classification "
            "(CoinMarketCap/Coinbase/Binance; zero LLM cost)."
        ),
    )
    parser.add_argument(
        "--with-derivatives",
        action="store_true",
        help=(
            "Also run 3c's derivatives (funding/OI/term-structure/options/VRP), "
            "CME COT, and on-chain/DeFi collection (zero LLM cost)."
        ),
    )
    parser.add_argument(
        "--with-macro",
        action="store_true",
        help=(
            "Also run 3f's macro matrix (CPI/PCE/claims/payrolls/yields/fed "
            "funds), forward-looking macro-event calendar, global liquidity "
            "(FRED M2/balance sheet/reverse repo) + BTC correlation to "
            "SP500/gold(PAXG)/DXY, the Upbit regional exchange premium, and "
            "the SEC EDGAR/congress.gov regulatory event calendar (zero LLM "
            "cost)."
        ),
    )
    parser.add_argument(
        "--with-asset-intelligence",
        action="store_true",
        help=(
            "Also run 3i's entity-flow intelligence (Nansen smart-money "
            "netflow, TOP_CANDIDATES only -- requires a prior --with-screening "
            "run and NANSEN_API_KEY), and network usage + developer-activity "
            "fundamentals (Etherscan tokentx-derived + GitHub, zero LLM cost)."
        ),
    )
    parser.add_argument(
        "--with-assessment",
        action="store_true",
        help=(
            "Also run 3d's multi-model current market assessment over 3b's "
            "latest TOP_CANDIDATES (requires OPENROUTER_API_KEY; a new, "
            "parallel evidence type distinct from --with-llm's llm_analyses)."
        ),
    )
    parser.add_argument(
        "--with-adversarial",
        action="store_true",
        help=(
            "Also run 3f's bull -> bear -> scenario adversarial research "
            "cycle over 3b's latest TOP_CANDIDATES (requires "
            "OPENROUTER_API_KEY and a prior --with-assessment run)."
        ),
    )
    parser.add_argument(
        "--with-judge",
        action="store_true",
        help=(
            "Also run 3e's Judge (synthesizes 3b/3c/3d/Phase-2 evidence into "
            "one decision per candidate), Risk Engine (deterministic sizing/"
            "gating), and Portfolio Construction (requires OPENROUTER_API_KEY "
            "and a prior --with-assessment run)."
        ),
    )
    parser.add_argument(
        "--evaluate-outcomes",
        action="store_true",
        help=(
            "Also run 3e's outcome-evaluation step: backfill realized_return/"
            "outcome_label on past-horizon decision_outcomes rows using "
            "actual subsequent market_snapshots. Independent of every other "
            "flag; zero LLM cost."
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    settings = get_settings()
    run_id = new_run_id()
    logger = setup_logging(run_id, settings.log_level)

    logger.info(
        "Starting run (with_llm=%s, with_screening=%s, with_derivatives=%s, "
        "with_macro=%s, with_assessment=%s, with_adversarial=%s, with_judge=%s, "
        "evaluate_outcomes=%s)",
        args.with_llm, args.with_screening, args.with_derivatives, args.with_macro,
        args.with_assessment, args.with_adversarial, args.with_judge, args.evaluate_outcomes,
    )

    try:
        client = get_supabase_client()
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    if args.with_llm:
        try:
            settings.require_openrouter()
        except RuntimeError as exc:
            logger.error(str(exc))
            return 1

    if args.with_assessment:
        try:
            settings.require_assessment()
        except RuntimeError as exc:
            logger.error(str(exc))
            return 1

    if args.with_adversarial:
        try:
            settings.require_adversarial()
        except RuntimeError as exc:
            logger.error(str(exc))
            return 1

    if args.with_judge:
        try:
            settings.require_judge()
        except RuntimeError as exc:
            logger.error(str(exc))
            return 1

    asset_repo = AssetRepository(client)
    snapshot_repo = MarketSnapshotRepository(client)

    market_service = MarketDataCollectionService(
        settings=settings,
        asset_repo=asset_repo,
        snapshot_repo=snapshot_repo,
        coingecko_client=CoinGeckoClient(settings),
    )
    market_result = market_service.run()

    logger.info("Market data run finished: %s", market_result.summary)
    if market_result.inserted:
        logger.info("Inserted snapshots for: %s", ", ".join(market_result.inserted))

    screening_failed = False
    if args.with_screening:
        screening_service = ScreeningService(
            settings=settings,
            asset_repo=asset_repo,
            asset_status_repo=AssetStatusRepository(client),
            screened_universe_repo=ScreenedUniverseRepository(client),
            regime_repo=MarketRegimeRepository(client),
            signal_source_repo=SignalSourceRepository(client),
            coingecko_client=CoinGeckoClient(settings),
            coinmarketcap_client=CoinMarketCapClient(settings),
            coinbase_client=CoinbaseClient(settings),
            binance_client=BinanceClient(settings),
        )
        screening_result = screening_service.run(run_id)
        logger.info("Screening finished: %s", screening_result.summary)
        if screening_result.anomalies:
            logger.warning("Anomaly flags: %s", screening_result.anomalies)
        screening_failed = screening_result.screened_count == 0

    if args.with_derivatives:
        derivatives_service = DerivativesService(
            asset_repo=asset_repo,
            evidence_repo=EvidenceObservationRepository(client),
            screened_universe_repo=ScreenedUniverseRepository(client),
            signal_source_repo=SignalSourceRepository(client),
            binance_client=BinanceClient(settings),
            deribit_client=DeribitClient(settings),
            cftc_client=CftcClient(settings),
            defillama_client=DefiLlamaClient(settings),
            etherscan_client=EtherscanClient(settings),
            glassnode_client=GlassnodeClient(settings),
        )
        derivatives_result = derivatives_service.run(run_id)
        logger.info("Derivatives/on-chain collection finished: %s", derivatives_result.summary)

    if args.with_macro:
        macro_service = MacroService(
            asset_repo=asset_repo,
            evidence_repo=EvidenceObservationRepository(client),
            signal_source_repo=SignalSourceRepository(client),
            fred_client=FredClient(settings),
            upbit_client=UpbitClient(settings),
            sec_edgar_client=SecEdgarClient(settings),
            congress_gov_client=CongressGovClient(settings),
            binance_client=BinanceClient(settings),
        )
        macro_result = macro_service.run(run_id)
        logger.info("Macro collection finished: %s", macro_result.summary)

    if args.with_asset_intelligence:
        asset_intelligence_service = AssetIntelligenceService(
            asset_repo=asset_repo,
            screened_universe_repo=ScreenedUniverseRepository(client),
            evidence_repo=EvidenceObservationRepository(client),
            signal_source_repo=SignalSourceRepository(client),
            nansen_client=NansenClient(settings),
            etherscan_client=EtherscanClient(settings),
            github_client=GitHubClient(settings),
        )
        asset_intelligence_result = asset_intelligence_service.run(run_id)
        logger.info("Asset intelligence collection finished: %s", asset_intelligence_result.summary)

    assessment_failed = False
    if args.with_assessment:
        api_key, assessment_models = settings.require_assessment()
        assessment_service = AssessmentService(
            settings=settings,
            asset_repo=asset_repo,
            screened_universe_repo=ScreenedUniverseRepository(client),
            regime_repo=MarketRegimeRepository(client),
            evidence_repo=EvidenceObservationRepository(client),
            news_repo=NewsRepository(client),
            asset_status_repo=AssetStatusRepository(client),
            snapshot_repo=snapshot_repo,
            prompt_template_repo=PromptTemplateRepository(client),
            assessment_repo=ModelMarketAssessmentRepository(client),
            cost_guard=CostGuard(settings, CostLedgerRepository(client)),
            providers=[
                OpenRouterAssessmentProvider(
                    name=name,
                    model=model,
                    api_key=api_key,
                    base_url=settings.openrouter_base_url,
                    timeout_seconds=settings.llm_request_timeout_seconds,
                )
                for name, model in assessment_models.items()
            ],
        )
        assessment_result = assessment_service.run(run_id)
        logger.info("Assessment finished: %s", assessment_result.summary)
        assessment_failed = bool(assessment_result.failed) and not assessment_result.stored_by_provider

    adversarial_failed = False
    if args.with_adversarial:
        adversarial_api_key, adversarial_model = settings.require_adversarial()
        adversarial_service = AdversarialService(
            settings=settings,
            asset_repo=asset_repo,
            screened_universe_repo=ScreenedUniverseRepository(client),
            regime_repo=MarketRegimeRepository(client),
            evidence_repo=EvidenceObservationRepository(client),
            assessment_repo=ModelMarketAssessmentRepository(client),
            prompt_template_repo=PromptTemplateRepository(client),
            adversarial_repo=AdversarialResearchRepository(client),
            cost_guard=CostGuard(settings, CostLedgerRepository(client)),
            provider=OpenRouterStructuredProvider(
                name="adversarial", model=adversarial_model, api_key=adversarial_api_key,
                base_url=settings.openrouter_base_url, timeout_seconds=settings.llm_request_timeout_seconds,
            ),
        )
        adversarial_result = adversarial_service.run(run_id)
        logger.info("Adversarial research finished: %s", adversarial_result.summary)
        adversarial_failed = bool(adversarial_result.failed) and adversarial_result.stored == 0

    judge_failed = False
    if args.with_judge:
        judge_api_key, judge_model = settings.require_judge()
        screened_universe_repo = ScreenedUniverseRepository(client)
        portfolio_position_repo = PortfolioPositionRepository(client)
        allocation_change_repo = PortfolioAllocationChangeRepository(client)
        holdings_ledger_repo = HoldingsLedgerRepository(client)

        judge_service = JudgeService(
            settings=settings,
            asset_repo=asset_repo,
            screened_universe_repo=screened_universe_repo,
            regime_repo=MarketRegimeRepository(client),
            evidence_repo=EvidenceObservationRepository(client),
            assessment_repo=ModelMarketAssessmentRepository(client),
            llm_analysis_repo=LLMAnalysisRepository(client),
            news_repo=NewsRepository(client),
            asset_status_repo=AssetStatusRepository(client),
            portfolio_position_repo=portfolio_position_repo,
            signal_source_repo=SignalSourceRepository(client),
            prompt_template_repo=PromptTemplateRepository(client),
            judge_decision_repo=JudgeDecisionRepository(client),
            decision_outcome_repo=DecisionOutcomeRepository(client),
            adversarial_repo=AdversarialResearchRepository(client),
            cost_guard=CostGuard(settings, CostLedgerRepository(client)),
            provider=OpenRouterJudgeProvider(
                name="judge",
                model=judge_model,
                api_key=judge_api_key,
                base_url=settings.openrouter_base_url,
                timeout_seconds=settings.llm_request_timeout_seconds,
            ),
        )
        judge_result = judge_service.run(run_id)
        logger.info("Judge finished: %s", judge_result.summary)
        judge_failed = bool(judge_result.failed) and judge_result.stored == 0

        if judge_result.decisions:
            risk_engine = RiskEngine(settings)
            assets_by_id = {a.id: a for a in asset_repo.get_active_assets()}

            # Phase 5a: current_allocation now comes SOLELY from real,
            # ground-truth holdings_ledger entries (quantity * real current
            # price, plus an explicit cash line) -- never from
            # portfolio_positions, which is retired as an input and only
            # written going forward as Portfolio Construction's own derived
            # bookkeeping (see README's Phase 5a section). Real prices are
            # looked up for every asset with a real holdings entry, not
            # just this run's candidates, so the total portfolio value used
            # to compute fractions is correct even for a long-term hold
            # that isn't a TOP_CANDIDATE this run.
            latest_holdings = holdings_ledger_repo.get_latest_holdings()
            price_lookup_ids = {a.id for a in assets_by_id.values()} | {
                h.asset_id for h in latest_holdings if h.asset_id is not None
            }
            price_by_asset_id: dict[str, float] = {}
            for aid in price_lookup_ids:
                snapshot = snapshot_repo.get_latest_snapshot(aid)
                if snapshot is not None:
                    price_by_asset_id[aid] = float(snapshot.price)
            current_allocations = compute_current_allocations(latest_holdings, price_by_asset_id)
            logger.info("Current allocations (from real holdings_ledger, ground truth): %s", current_allocations)

            sized_decisions = []
            decisions_by_asset = {}
            decision_ids_by_asset = {}
            returns_by_symbol = {}
            lookback_start = datetime.now(UTC) - timedelta(days=31)

            for decision in judge_result.decisions:
                asset = assets_by_id.get(decision.asset_id)
                symbol = asset.symbol if asset else decision.asset_id
                screened = screened_universe_repo.get_latest_for_symbol(symbol) if asset else None
                current_allocation = current_allocations.get(decision.asset_id, 0.0)
                sized = risk_engine.size_one(
                    decision, symbol,
                    screened.volatility_30d if screened else None,
                    current_allocation,
                )
                sized_decisions.append(sized)
                decisions_by_asset[decision.asset_id] = decision
                decision_ids_by_asset[decision.asset_id] = decision.id

                closes = [
                    float(s.price)
                    for s in snapshot_repo.get_snapshots_in_range(
                        decision.asset_id, lookback_start, datetime.now(UTC)
                    )
                ]
                if closes:
                    returns_by_symbol[symbol] = compute_daily_returns(closes)

            risk_engine.flag_correlations(sized_decisions, returns_by_symbol)
            correlation_flags = [(d.symbol, d.correlation_reason) for d in sized_decisions if d.correlation_flagged]
            if correlation_flags:
                logger.warning("Correlation-concentration flags: %s", correlation_flags)

            turnover_used = allocation_change_repo.get_turnover_since(
                datetime.now(UTC) - timedelta(days=7)
            )
            risk_engine.apply_turnover_cap(sized_decisions, turnover_used)
            turnover_capped = [d.symbol for d in sized_decisions if d.turnover_capped]
            if turnover_capped:
                logger.warning("Turnover-capped this run: %s", turnover_capped)

            portfolio_service = PortfolioConstructionService(
                settings=settings,
                position_repo=portfolio_position_repo,
                allocation_change_repo=allocation_change_repo,
            )
            actions = portfolio_service.apply(run_id, sized_decisions, decisions_by_asset, decision_ids_by_asset)
            logger.info(
                "Portfolio actions: %s",
                [(a.symbol, a.action, round(a.new_allocation, 4)) for a in actions],
            )

    if args.evaluate_outcomes:
        evaluation_service = OutcomeEvaluationService(
            decision_outcome_repo=DecisionOutcomeRepository(client),
            snapshot_repo=snapshot_repo,
        )
        evaluation_result = evaluation_service.run()
        logger.info("Outcome evaluation finished: %s", evaluation_result.summary)

    exit_code = 1 if (
        market_result.failed or screening_failed or assessment_failed or adversarial_failed or judge_failed
    ) else 0

    if not args.with_llm:
        if market_result.failed:
            logger.warning("Failures: %s", market_result.failed)
        return exit_code

    news_repo = NewsRepository(client)
    news_service = NewsCollectionService(
        asset_repo=asset_repo,
        news_repo=news_repo,
        rss_client=RssClient(),
    )
    news_result = news_service.run()
    logger.info("News collection finished: %s", news_result.summary)

    llm_repo = LLMAnalysisRepository(client)
    providers = [
        OpenRouterProvider(
            name="claude",
            model=settings.claude_model,
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
        OpenRouterProvider(
            name="openai",
            model=settings.openai_model,
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
        OpenRouterProvider(
            name="gemini",
            model=settings.gemini_model,
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.llm_request_timeout_seconds,
        ),
    ]

    llm_service = LLMResearchService(
        settings=settings,
        asset_repo=asset_repo,
        snapshot_repo=snapshot_repo,
        news_repo=news_repo,
        llm_repo=llm_repo,
        cost_guard=CostGuard(settings, CostLedgerRepository(client)),
        providers=providers,
    )
    llm_result = llm_service.run(run_id)
    logger.info("LLM research finished: %s", llm_result.summary)

    if (
        market_result.failed or llm_result.failed or screening_failed or assessment_failed
        or adversarial_failed or judge_failed
    ):
        logger.warning(
            "Market failures: %s | LLM failures: %s | Screening failed: %s | "
            "Assessment failed: %s | Adversarial failed: %s | Judge failed: %s",
            market_result.failed, llm_result.failed, screening_failed,
            assessment_failed, adversarial_failed, judge_failed,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
