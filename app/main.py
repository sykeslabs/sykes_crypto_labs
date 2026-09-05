import argparse
import sys

from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import (
    AssetRepository,
    AssetStatusRepository,
    EvidenceObservationRepository,
    LLMAnalysisRepository,
    MarketRegimeRepository,
    MarketSnapshotRepository,
    ModelMarketAssessmentRepository,
    NewsRepository,
    PromptTemplateRepository,
    ScreenedUniverseRepository,
    SignalSourceRepository,
)
from app.llm.assessment_provider import OpenRouterAssessmentProvider
from app.llm.assessment_service import AssessmentService
from app.llm.cost import CostGuard, CostLedgerRepository
from app.llm.openrouter_client import OpenRouterProvider
from app.llm.service import LLMResearchService
from app.logging_config import new_run_id, setup_logging
from app.market_data.binance import BinanceClient
from app.market_data.cftc import CftcClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.coingecko import CoinGeckoClient
from app.market_data.coinmarketcap import CoinMarketCapClient
from app.market_data.defillama import DefiLlamaClient
from app.market_data.deribit import DeribitClient
from app.market_data.derivatives_service import DerivativesService
from app.market_data.etherscan import EtherscanClient
from app.market_data.glassnode import GlassnodeClient
from app.market_data.screening_service import ScreeningService
from app.market_data.service import MarketDataCollectionService
from app.news.rss_client import RssClient
from app.news.service import NewsCollectionService


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
        "--with-assessment",
        action="store_true",
        help=(
            "Also run 3d's multi-model current market assessment over 3b's "
            "latest TOP_CANDIDATES (requires OPENROUTER_API_KEY; a new, "
            "parallel evidence type distinct from --with-llm's llm_analyses)."
        ),
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    settings = get_settings()
    run_id = new_run_id()
    logger = setup_logging(run_id, settings.log_level)

    logger.info(
        "Starting run (with_llm=%s, with_screening=%s, with_derivatives=%s, with_assessment=%s)",
        args.with_llm, args.with_screening, args.with_derivatives, args.with_assessment,
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

    exit_code = 1 if (market_result.failed or screening_failed or assessment_failed) else 0

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

    if market_result.failed or llm_result.failed or screening_failed or assessment_failed:
        logger.warning(
            "Market failures: %s | LLM failures: %s | Screening failed: %s | Assessment failed: %s",
            market_result.failed, llm_result.failed, screening_failed, assessment_failed,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
