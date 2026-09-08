"""Phase 5: shared FastAPI dependencies — the Supabase client and every
repository this read/query layer needs. Reuses the exact same
`get_supabase_client()`/repository classes the CLI pipeline already uses;
this layer adds no new database-access code, only new read methods on
existing repositories (see `app/database/repository.py`).
"""

from supabase import Client

from app.config import Settings, get_settings
from app.database.client import get_supabase_client
from app.database.repository import (
    AdversarialResearchRepository,
    AssetRepository,
    AssetStatusRepository,
    CalibrationRunRepository,
    DecisionOutcomeRepository,
    EvidenceValueReportRepository,
    HoldingsLedgerRepository,
    JudgeDecisionRepository,
    JudgeReasoningAuditRepository,
    LLMAnalysisRepository,
    MarketRegimeRepository,
    MarketSnapshotRepository,
    ModelMarketAssessmentRepository,
    NewsRepository,
    PortfolioPositionRepository,
    ScreenedUniverseRepository,
    SignalSourceRepository,
)
from app.llm.cost import CostLedgerRepository
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.coingecko import CoinGeckoClient


def get_client() -> Client:
    return get_supabase_client()


def get_settings_dependency() -> Settings:
    return get_settings()


def get_asset_repo() -> AssetRepository:
    return AssetRepository(get_client())


def get_asset_status_repo() -> AssetStatusRepository:
    return AssetStatusRepository(get_client())


def get_screened_universe_repo() -> ScreenedUniverseRepository:
    return ScreenedUniverseRepository(get_client())


def get_regime_repo() -> MarketRegimeRepository:
    return MarketRegimeRepository(get_client())


def get_assessment_repo() -> ModelMarketAssessmentRepository:
    return ModelMarketAssessmentRepository(get_client())


def get_adversarial_repo() -> AdversarialResearchRepository:
    return AdversarialResearchRepository(get_client())


def get_judge_decision_repo() -> JudgeDecisionRepository:
    return JudgeDecisionRepository(get_client())


def get_reasoning_audit_repo() -> JudgeReasoningAuditRepository:
    return JudgeReasoningAuditRepository(get_client())


def get_decision_outcome_repo() -> DecisionOutcomeRepository:
    return DecisionOutcomeRepository(get_client())


def get_calibration_run_repo() -> CalibrationRunRepository:
    return CalibrationRunRepository(get_client())


def get_evidence_value_report_repo() -> EvidenceValueReportRepository:
    return EvidenceValueReportRepository(get_client())


def get_portfolio_position_repo() -> PortfolioPositionRepository:
    return PortfolioPositionRepository(get_client())


def get_holdings_ledger_repo() -> HoldingsLedgerRepository:
    return HoldingsLedgerRepository(get_client())


def get_market_snapshot_repo() -> MarketSnapshotRepository:
    return MarketSnapshotRepository(get_client())


def get_signal_source_repo() -> SignalSourceRepository:
    return SignalSourceRepository(get_client())


def get_cost_ledger_repo() -> CostLedgerRepository:
    return CostLedgerRepository(get_client())


def get_llm_analysis_repo() -> LLMAnalysisRepository:
    return LLMAnalysisRepository(get_client())


def get_news_repo() -> NewsRepository:
    return NewsRepository(get_client())


def get_binance_client() -> BinanceClient:
    return BinanceClient(get_settings())


def get_coinbase_client() -> CoinbaseClient:
    return CoinbaseClient(get_settings())


def get_coingecko_client() -> CoinGeckoClient:
    return CoinGeckoClient(get_settings())
