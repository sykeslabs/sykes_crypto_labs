"""Phase 3e.1: retroactive historical replay. Re-runs the SAME model-
assessment -> Judge -> Risk Engine -> Portfolio Construction pipeline 3e
already built, unmodified, against a past date range — using only evidence
that can be honestly reconstructed as it would have looked at that past
date (see `EVIDENCE_UNAVAILABLE_FOR_REPLAY` below for exactly what can't be
and is therefore marked UNAVAILABLE, never fabricated).

Safety: Risk Engine / Portfolio Construction run against a fully isolated,
in-memory-only simulated portfolio state (`app/benchmarks/replay_fakes.py`)
— a backfill run never reads or writes the live `portfolio_positions`/
`portfolio_allocation_changes` tables. `judge_decisions`/`decision_outcomes`
rows ARE persisted for real (that's the whole point), always tagged
`is_backfilled = true` and `in_holdout_window = false` (backfilled rows are
never forward-tracked evidence — see PHASE3E1_PROMPT.md's non-negotiables).
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.benchmarks.historical_factors import (
    TRAILING_WINDOW_DAYS,
    HistoricalSeries,
    PointInTimeFactors,
    compute_point_in_time_factors,
    pct_change,
)
from app.benchmarks.replay_fakes import (
    AsOfAssetStatusRepo,
    AsOfLLMAnalysisRepo,
    InMemoryAllocationChangeRepo,
    InMemoryPortfolioPositionRepo,
    StaticAssessmentRepo,
    StaticEvidenceRepo,
    StaticRegimeRepo,
    StaticSnapshotRepo,
)
from app.benchmarks.schemas import DecisionOutcome
from app.benchmarks.triple_barrier import compute_target_stop_thresholds, evaluate_triple_barrier
from app.config import Settings
from app.database.evidence_provenance import DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE
from app.database.models import Asset
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
from app.judge.context import SYSTEM_PROMPT_TEMPLATE as JUDGE_SYSTEM_PROMPT_TEMPLATE
from app.judge.context import build_judge_context
from app.judge.context import render_prompt as render_judge_prompt
from app.judge.provider import OpenRouterJudgeProvider
from app.judge.schemas import JudgeDecisionRecord
from app.llm.assessment_context import SYSTEM_PROMPT_TEMPLATE as ASSESSMENT_SYSTEM_PROMPT_TEMPLATE
from app.llm.assessment_context import build_assessment_context
from app.llm.assessment_context import render_prompt as render_assessment_prompt
from app.llm.assessment_provider import OpenRouterAssessmentProvider
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.llm.cost import CostGuard
from app.market_data.evidence_schemas import EvidenceObservation
from app.market_data.factors import compute_composite_factor_scores
from app.market_data.regime import classify_risk_regime, compute_breadth_pct, compute_halving_cycle_days, moving_average
from app.market_data.schemas import MarketSnapshot
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset
from app.portfolio.construction import PortfolioConstructionService
from app.risk.correlation import compute_daily_returns
from app.risk.engine import RiskEngine

logger = logging.getLogger("crypto_ai_portfolio.benchmarks")

PROMPT_TEMPLATE_NAME_ASSESSMENT = "market_assessment"
PROMPT_TEMPLATE_NAME_JUDGE = "judge_decision"

# Task 1's evidence-feasibility classification, made concrete: everything
# 3c would normally supply EXCEPT Binance's genuinely historical funding-rate
# series (verified live: /fapi/v1/fundingRate returns real past
# observations, not today's rate backdated) is NOT reconstructed for replay
# — these providers only serve current, already-corrected state for a past
# date, which would be exactly the hindsight-inflation problem this
# sub-phase exists to avoid. Disclosed to the Judge every replayed day via
# `unavailable_sources`, never silently omitted.
EVIDENCE_UNAVAILABLE_FOR_REPLAY: list[str] = [
    "FUTURES_TERM_STRUCTURE",       # Binance/Deribit dated-futures basis/carry
    "AGGREGATE_OPEN_INTEREST",
    "Deribit",                      # options IV/skew, volatility risk premium
    "CME_COT_POSITIONING",
    "DefiLlama",                    # protocol TVL flows
    "STABLECOIN_SUPPLY_VELOCITY_AND_EXCHANGE_RESERVES",
    "Etherscan",                    # large-transfer proxy
    "ON_CHAIN_VALUATION_METRICS",
    "ON_CHAIN_MINER_METRICS",
    "SPOT_ETF_FLOWS",
    "PREDICTION_MARKETS",
    "TOKEN_UNLOCK_SCHEDULE",
    # Regime-level: needs CoinMarketCap's 90d percent-change field and/or
    # universe-wide historical market cap — neither is a fixed, reconstructable
    # value for a past date with this system's current sources.
    "BTC_DOMINANCE",
    "ALTCOIN_SEASON_INDEX",
]

# Observed live per-batched-call costs (3d: 3 models x 1 call; 3e: 1 model x
# 1 call), same sizing methodology 3d/3e themselves used before merging.
OBSERVED_ASSESSMENT_COST_PER_DAY = Decimal("0.42")
OBSERVED_JUDGE_COST_PER_DAY = Decimal("0.155")
OBSERVED_COST_PER_REPLAYED_DAY = OBSERVED_ASSESSMENT_COST_PER_DAY + OBSERVED_JUDGE_COST_PER_DAY


def estimate_replay_cost(num_days: int) -> Decimal:
    """Same sizing methodology 3d/3e used before merging: observed
    live cost per batched call x expected call volume."""
    return OBSERVED_COST_PER_REPLAYED_DAY * num_days


@dataclass
class ReplayDayResult:
    date: str
    candidates: list[str] = field(default_factory=list)
    decisions_stored: int = 0
    outcomes_resolved_immediately: int = 0
    cost: Decimal = Decimal("0")
    skipped_cost_cap: bool = False
    error: str | None = None


@dataclass
class ReplayResult:
    days: list[ReplayDayResult] = field(default_factory=list)
    total_cost: Decimal = Decimal("0")
    stopped_early_reason: str | None = None

    @property
    def summary(self) -> str:
        return (
            f"days_run={len(self.days)} total_decisions="
            f"{sum(d.decisions_stored for d in self.days)} total_cost=${self.total_cost} "
            f"stopped_early={self.stopped_early_reason}"
        )


class HistoricalReplayService:
    def __init__(
        self,
        settings: Settings,
        asset_repo: AssetRepository,
        news_repo: NewsRepository,
        llm_analysis_repo: LLMAnalysisRepository,
        asset_status_repo: AssetStatusRepository,
        signal_source_repo: SignalSourceRepository,
        prompt_template_repo: PromptTemplateRepository,
        judge_decision_repo: JudgeDecisionRepository,
        decision_outcome_repo: DecisionOutcomeRepository,
        cost_guard: CostGuard,
        assessment_providers: list[OpenRouterAssessmentProvider],
        judge_provider: OpenRouterJudgeProvider,
        historical_series_fetcher,
        funding_rate_fetcher,
    ) -> None:
        self._settings = settings
        self._asset_repo = asset_repo
        self._news_repo = news_repo
        self._llm_analysis_repo = llm_analysis_repo
        self._asset_status_repo = asset_status_repo
        self._signal_source_repo = signal_source_repo
        self._prompt_template_repo = prompt_template_repo
        self._judge_decision_repo = judge_decision_repo
        self._decision_outcome_repo = decision_outcome_repo
        self._cost_guard = cost_guard
        self._assessment_providers = assessment_providers
        self._judge_provider = judge_provider
        self._fetch_series = historical_series_fetcher  # (Asset) -> HistoricalSeries | None
        self._fetch_funding = funding_rate_fetcher  # (Asset) -> list[dict] (may be empty)
        # Tracked in-process because the assessment stage's real cost is
        # never persisted to any COST_TRACKED_TABLES entry (in-memory only,
        # by design) — CostGuard's DB-backed check() alone can't see it
        # accumulating call-to-call within one long-running invocation. Set
        # once per run() call from the real remaining budget at start, then
        # decremented locally as real cost is actually incurred.
        self._local_daily_budget = Decimal("0")
        self._local_monthly_budget = Decimal("0")
        self._local_spent = Decimal("0")

    def _check_budget(self) -> tuple[bool, str | None]:
        if self._local_spent >= self._local_daily_budget:
            return False, (
                f"Replay's own spend this run (${self._local_spent}) has used up the daily "
                f"budget that was available when it started (${self._local_daily_budget})"
            )
        if self._local_spent >= self._local_monthly_budget:
            return False, (
                f"Replay's own spend this run (${self._local_spent}) has used up the monthly "
                f"budget that was available when it started (${self._local_monthly_budget})"
            )
        # Still consult the real ledger too — catches OTHER concurrent
        # activity (a live pipeline run, etc.) hitting the cap independently.
        return self._cost_guard.check()

    def run(self, start_date: datetime, end_date: datetime) -> ReplayResult:
        result = ReplayResult()
        self._local_daily_budget, self._local_monthly_budget = self._cost_guard.remaining_budget()
        self._local_spent = Decimal("0")
        active_assets = self._asset_repo.get_active_assets()
        assets_by_id = {a.id: a for a in active_assets}

        series_by_asset = {}
        for asset in active_assets:
            series = self._fetch_series(asset)
            if series is not None:
                series_by_asset[asset.id] = series
        if "BTC" not in {a.symbol for a in active_assets if a.id in series_by_asset}:
            logger.error("BTC has no historical series — cannot compute relative strength/regime. Aborting.")
            result.stopped_early_reason = "BTC historical series unavailable"
            return result

        funding_by_asset = {a.id: self._fetch_funding(a) for a in active_assets}

        portfolio_position_repo = InMemoryPortfolioPositionRepo()
        allocation_change_repo = InMemoryAllocationChangeRepo()
        risk_engine = RiskEngine(self._settings)
        portfolio_service = PortfolioConstructionService(self._settings, portfolio_position_repo, allocation_change_repo)

        prompt_template_id_assessment = self._prompt_template_repo.get_or_create(
            name=PROMPT_TEMPLATE_NAME_ASSESSMENT, stage="3d",
            version=self._settings.assessment_prompt_version,
            template_hash=_hash(ASSESSMENT_SYSTEM_PROMPT_TEMPLATE),
        )
        prompt_template_id_judge = self._prompt_template_repo.get_or_create(
            name=PROMPT_TEMPLATE_NAME_JUDGE, stage="3e",
            version=self._settings.judge_prompt_version,
            template_hash=_hash(JUDGE_SYSTEM_PROMPT_TEMPLATE),
        )

        for cutoff in _daily_cutoffs(start_date, end_date):
            day_result = self._replay_one_day(
                cutoff, active_assets, assets_by_id, series_by_asset, funding_by_asset,
                risk_engine, portfolio_service, portfolio_position_repo, allocation_change_repo,
                prompt_template_id_assessment, prompt_template_id_judge,
            )
            result.days.append(day_result)
            result.total_cost += day_result.cost
            if day_result.skipped_cost_cap:
                result.stopped_early_reason = "CostGuard cap reached"
                logger.warning("Replay stopped early at %s: cost cap reached", day_result.date)
                break

        logger.info("Replay complete: %s", result.summary)
        return result

    def _replay_one_day(
        self, cutoff, active_assets, assets_by_id, series_by_asset, funding_by_asset,
        risk_engine, portfolio_service, portfolio_position_repo, allocation_change_repo,
        prompt_template_id_assessment, prompt_template_id_judge,
    ) -> ReplayDayResult:
        day_result = ReplayDayResult(date=cutoff.date().isoformat())
        day_run_id = f"BACKFILL-{cutoff.date().isoformat()}"

        allowed, reason = self._check_budget()
        if not allowed:
            day_result.skipped_cost_cap = True
            return day_result

        factors_by_asset, screened_by_asset = self._build_day_universe(cutoff, active_assets, series_by_asset)
        candidates = [s for s in screened_by_asset.values() if s.is_top_candidate]
        day_result.candidates = [c.symbol for c in candidates]
        if not candidates:
            return day_result

        regime = self._build_regime(cutoff, active_assets, screened_by_asset, series_by_asset)
        snapshot_repo = StaticSnapshotRepo({
            asset_id: self._build_snapshot_history(cutoff, asset_id, series_by_asset.get(asset_id))
            for asset_id in assets_by_id
        })
        evidence_repo = StaticEvidenceRepo({
            asset_id: self._build_evidence(cutoff, asset_id, funding_by_asset.get(asset_id, []))
            for asset_id in assets_by_id
        })
        as_of_status_repo = AsOfAssetStatusRepo(self._asset_status_repo, cutoff)
        as_of_llm_repo = AsOfLLMAnalysisRepo(self._llm_analysis_repo, cutoff)

        assessment_context = build_assessment_context(
            day_run_id, self._settings, candidates, assets_by_id,
            snapshot_repo, StaticRegimeRepo(regime), evidence_repo,
            self._news_repo, as_of_status_repo, as_of=cutoff,
        )
        if not assessment_context.assets:
            return day_result

        system_prompt, user_prompt = render_assessment_prompt(assessment_context, self._settings.assessment_prompt_version)
        symbol_to_asset = {ac.asset.symbol: ac.asset for ac in assessment_context.assets}

        assessment_records: list[ModelMarketAssessmentRecord] = []
        for provider in self._assessment_providers:
            allowed, reason = self._check_budget()
            if not allowed:
                day_result.skipped_cost_cap = True
                return day_result

            provider_result = provider.analyze(system_prompt, user_prompt)
            day_result.cost += provider_result.estimated_cost
            self._local_spent += provider_result.estimated_cost
            if provider_result.error is not None or provider_result.batch is None:
                logger.warning("%s (backfill %s): %s", provider.name, day_result.date, provider_result.error)
                continue

            items = provider_result.batch.assessments
            if not items:
                continue
            per_item_cost = provider_result.estimated_cost / len(items)
            for item in items:
                asset = symbol_to_asset.get(item.asset)
                if asset is None:
                    continue
                assessment_records.append(ModelMarketAssessmentRecord(
                    run_id=day_run_id, asset_id=asset.id, provider=provider_result.provider,
                    model=provider_result.model, prompt_template_id=None,
                    assessment_timestamp=cutoff, data_cutoff_timestamp=cutoff,
                    short_term_direction=item.direction.short_term, medium_term_direction=item.direction.medium_term,
                    long_term_direction=item.direction.long_term,
                    short_term_confidence=item.confidence.short_term, medium_term_confidence=item.confidence.medium_term,
                    long_term_confidence=item.confidence.long_term,
                    expected_return_7d=item.expected_return.return_7d, expected_return_30d=item.expected_return.return_30d,
                    expected_return_90d=item.expected_return.return_90d,
                    risk_score=item.risk.score, risk_level=item.risk.level, market_regime=item.market_regime,
                    model_agreement=1.0,  # overwritten below once every provider's response is in
                    overall_assessment=item.overall_assessment, thesis=item.thesis,
                    key_drivers=[d.model_dump() for d in item.key_drivers],
                    key_risks=[d.model_dump() for d in item.key_risks],
                    source_assessment=[d.model_dump() for d in item.source_assessment],
                    invalidation_conditions=item.invalidation_conditions,
                    raw_response=None, estimated_cost=per_item_cost,
                ))

        if not assessment_records:
            return day_result
        _assign_model_agreement(assessment_records)

        judge_context = build_judge_context(
            day_run_id, self._settings, candidates, assets_by_id,
            StaticRegimeRepo(regime), evidence_repo, StaticAssessmentRepo(assessment_records),
            as_of_llm_repo, self._news_repo, as_of_status_repo,
            portfolio_position_repo, self._signal_source_repo, as_of=cutoff,
        )
        judge_context.unavailable_sources = sorted(set(judge_context.unavailable_sources) | set(EVIDENCE_UNAVAILABLE_FOR_REPLAY))
        if not judge_context.assets:
            return day_result

        allowed, reason = self._check_budget()
        if not allowed:
            day_result.skipped_cost_cap = True
            return day_result

        system_prompt, user_prompt = render_judge_prompt(judge_context, self._settings.judge_prompt_version)
        provider_result = self._judge_provider.decide(system_prompt, user_prompt)
        day_result.cost += provider_result.estimated_cost
        self._local_spent += provider_result.estimated_cost
        if provider_result.error is not None or provider_result.batch is None:
            day_result.error = provider_result.error
            return day_result

        symbol_to_context = {ac.asset.symbol: ac for ac in judge_context.assets}
        stored_decisions: list[JudgeDecisionRecord] = []
        items = provider_result.batch.decisions
        per_item_cost = provider_result.estimated_cost / len(items) if items else Decimal("0")

        for item in items:
            ac = symbol_to_context.get(item.asset)
            if ac is None:
                continue

            record = JudgeDecisionRecord(
                # created_at is the row's REAL insertion time, not the
                # simulated historical date (`cutoff`) — CostGuard sums
                # cost by created_at >= today's midnight, so a historical
                # date here would make this row invisible to the daily/
                # monthly cap check (a real bug, found live: see README).
                # The simulated date is still fully recoverable from run_id
                # (e.g. "BACKFILL-2026-08-09").
                run_id=day_run_id, asset_id=ac.asset.id, created_at=datetime.now(UTC),
                decision=item.decision, confidence=item.confidence, target_allocation=item.target_allocation,
                expected_return=item.expected_return, expected_alpha=item.expected_alpha,
                risk_score=item.risk_score, uncertainty=item.uncertainty,
                model_agreement=item.model_agreement, source_agreement=item.source_agreement,
                investment_horizon_days=item.investment_horizon_days,
                key_evidence=item.key_evidence, contradictory_evidence=item.contradictory_evidence,
                key_risks=item.key_risks, invalidation_conditions=item.invalidation_conditions,
                requires_review=item.requires_review, thesis=item.thesis,
                regime_id=None, prompt_template_id=prompt_template_id_judge,
                estimated_cost=per_item_cost, is_backfilled=True,
            )
            decision_id = self._judge_decision_repo.insert(record)
            record.id = decision_id
            stored_decisions.append(record)
            day_result.decisions_stored += 1

            target_return, stop_return = compute_target_stop_thresholds(item.expected_return, item.risk_score)
            outcome = DecisionOutcome(
                decision_id=decision_id, asset_id=ac.asset.id, decision_timestamp=cutoff,
                horizon_days=item.investment_horizon_days, target_return=target_return, stop_return=stop_return,
                outcome_label="UNRESOLVED", regime_at_decision=None, judge_confidence=item.confidence,
                in_holdout_window=False, is_backfilled=True,
            )
            self._decision_outcome_repo.insert(outcome)

            resolved = self._resolve_backfilled_outcome(
                series_by_asset.get(ac.asset.id), cutoff, item.investment_horizon_days, target_return, stop_return,
            )
            if resolved is not None:
                label, realized_return, evaluated_at = resolved
                self._decision_outcome_repo.update_outcome(decision_id, realized_return, label, evaluated_at)
                day_result.outcomes_resolved_immediately += 1

        # Risk Engine + Portfolio Construction, against the isolated in-memory
        # simulated portfolio state only — never the live tables.
        if stored_decisions:
            current_positions = portfolio_position_repo.get_all()
            sized_decisions, decisions_by_asset, decision_ids_by_asset, returns_by_symbol = [], {}, {}, {}
            for record in stored_decisions:
                symbol = assets_by_id[record.asset_id].symbol
                current_allocation = (
                    current_positions[record.asset_id].current_allocation
                    if record.asset_id in current_positions else 0.0
                )
                factors = factors_by_asset.get(record.asset_id)
                sized = risk_engine.size_one(record, symbol, factors.volatility_30d if factors else None, current_allocation)
                sized_decisions.append(sized)
                decisions_by_asset[record.asset_id] = record
                decision_ids_by_asset[record.asset_id] = record.id

                series = series_by_asset.get(record.asset_id)
                if series is not None:
                    _, closes, _ = series.as_of(cutoff)
                    if len(closes) >= 2:
                        returns_by_symbol[symbol] = compute_daily_returns(closes[-TRAILING_WINDOW_DAYS:])

            risk_engine.flag_correlations(sized_decisions, returns_by_symbol)
            turnover_used = allocation_change_repo.get_turnover_since(cutoff - timedelta(days=7))
            risk_engine.apply_turnover_cap(sized_decisions, turnover_used)
            portfolio_service.apply(day_run_id, sized_decisions, decisions_by_asset, decision_ids_by_asset)

        return day_result

    def _build_day_universe(
        self, cutoff: datetime, active_assets: list[Asset], series_by_asset: dict[str, HistoricalSeries]
    ) -> tuple[dict[str, PointInTimeFactors], dict[str, ScreenedAsset]]:
        btc_asset = next((a for a in active_assets if a.symbol == "BTC"), None)
        btc_series = series_by_asset.get(btc_asset.id) if btc_asset else None
        btc_momentum_30d = None
        if btc_series is not None:
            _, btc_closes, _ = btc_series.as_of(cutoff)
            btc_momentum_30d = pct_change(btc_closes, 30)

        factors_by_asset: dict[str, PointInTimeFactors] = {}
        factor_rows: list[dict] = []
        assets_in_order: list[Asset] = []
        for asset in active_assets:
            series = series_by_asset.get(asset.id)
            if series is None:
                continue
            factors = compute_point_in_time_factors(series, cutoff, btc_momentum_30d)
            if factors.price is None:
                continue
            factors_by_asset[asset.id] = factors
            assets_in_order.append(asset)
            factor_rows.append({
                "momentum_30d": factors.momentum_30d, "momentum_7d": factors.momentum_7d,
                "relative_strength_30d": factors.relative_strength_30d,
                "volatility_30d": factors.volatility_30d, "drawdown_30d": factors.drawdown_30d,
                "volume_24h": factors.volume_24h_proxy,
            })

        scores = compute_composite_factor_scores(factor_rows)
        screened_by_asset: dict[str, ScreenedAsset] = {}
        for asset, score, factors in zip(assets_in_order, scores, (factors_by_asset[a.id] for a in assets_in_order), strict=True):
            screened_by_asset[asset.id] = ScreenedAsset(
                run_id=f"BACKFILL-{cutoff.date().isoformat()}", computed_at=cutoff, symbol=asset.symbol,
                coingecko_id=asset.coingecko_id, asset_id=asset.id,
                momentum_7d=factors.momentum_7d, momentum_30d=factors.momentum_30d,
                volatility_30d=factors.volatility_30d, drawdown_30d=factors.drawdown_30d,
                volatility_drawdown_source=series_by_asset[asset.id].source,
                relative_strength_30d=factors.relative_strength_30d,
                composite_factor_score=score, anomaly_flag=factors.anomaly_flag,
                anomaly_reason=factors.anomaly_reason, volume_24h=factors.volume_24h_proxy,
            )

        ranked = sorted(
            screened_by_asset.values(),
            key=lambda s: (s.composite_factor_score is None, -(s.composite_factor_score or 0)),
        )
        for rank, s in enumerate(ranked, start=1):
            s.rank = rank
            s.is_top_candidate = rank <= self._settings.top_candidates_size

        return factors_by_asset, screened_by_asset

    def _build_regime(self, cutoff, active_assets, screened_by_asset, series_by_asset) -> MarketRegimeSnapshot:
        btc_asset = next((a for a in active_assets if a.symbol == "BTC"), None)
        btc_series = series_by_asset.get(btc_asset.id) if btc_asset else None
        btc_closes: list[float] = []
        if btc_series is not None:
            _, btc_closes, _ = btc_series.as_of(cutoff)

        breadth_pct = compute_breadth_pct([s.momentum_30d for s in screened_by_asset.values()])
        ma7 = moving_average(btc_closes, 7) if btc_closes else None
        ma30 = moving_average(btc_closes, min(30, len(btc_closes))) if btc_closes else None
        regime = classify_risk_regime(btc_closes[-1], ma7, ma30, breadth_pct) if (btc_closes and ma7 and ma30) else None

        days_since_halving, days_until_halving = compute_halving_cycle_days(cutoff.date())

        return MarketRegimeSnapshot(
            id=None, run_id=f"BACKFILL-{cutoff.date().isoformat()}", computed_at=cutoff, regime=regime,
            inputs={
                "btc_price": btc_closes[-1] if btc_closes else None, "btc_ma7": ma7, "btc_ma30": ma30,
                "breadth_pct": breadth_pct, "btc_dominance": None, "altcoin_season_index": None,
                "days_since_halving": days_since_halving, "days_until_next_halving_estimated": days_until_halving,
            },
            notes="btc_dominance/altcoin_season_index UNAVAILABLE for replay — not point-in-time reconstructable (see README).",
        )

    def _build_snapshot_history(self, cutoff, asset_id, series: HistoricalSeries | None) -> list[MarketSnapshot]:
        if series is None:
            return []
        dates, closes, volumes = series.as_of(cutoff)
        if not closes:
            return []
        trailing = list(zip(dates, closes, volumes, strict=True))[-10:]
        trailing.reverse()  # newest-first, matching the real repo's contract
        rows = []
        for i, (d, close, volume) in enumerate(trailing):
            is_latest = i == 0
            rows.append(MarketSnapshot(
                asset_id=asset_id, timestamp=d, price=close, market_cap=None,
                volume_24h=close * volume if volume else None,
                price_change_24h=pct_change(closes, 1) if is_latest else None,
                price_change_7d=pct_change(closes, 7) if is_latest else None,
                price_change_30d=pct_change(closes, 30) if is_latest else None,
                source="binance_or_coinbase_historical_replay",
            ))
        return rows

    def _build_evidence(self, cutoff, asset_id, funding_records: list[dict]) -> list[EvidenceObservation]:
        candidates = [r for r in funding_records if r["funding_time"] <= cutoff]
        if not candidates:
            return []
        latest = max(candidates, key=lambda r: r["funding_time"])
        return [EvidenceObservation(
            source="binance_funding_rate", asset_id=asset_id, scope="ASSET",
            observation_timestamp=latest["funding_time"], publication_timestamp=None,
            retrieval_timestamp=cutoff, timeframe=None, is_revision_of=None,
            freshness="RECENT", decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["binance_funding_rate"],
            status="OK", payload={"funding_rate": latest["funding_rate"]},
        )]

    def _resolve_backfilled_outcome(
        self, series: HistoricalSeries | None, decision_timestamp: datetime,
        horizon_days: int, target_return: float, stop_return: float,
    ) -> tuple[str, float, datetime] | None:
        """Reuses `evaluate_triple_barrier` directly (task 5) — but fed from
        this replay's own fetched historical series, not the live
        `market_snapshots` table (which only has ~days of real history and
        would silently under-resolve almost every backfilled decision)."""
        if series is None:
            return None
        horizon_end = decision_timestamp + timedelta(days=horizon_days)
        entry_price = None
        price_points = []
        for d, close in zip(series.dates, series.closes, strict=True):
            if d < decision_timestamp:
                continue
            if entry_price is None:
                entry_price = close
                continue
            price_points.append((d, close))
        if entry_price is None:
            return None

        label, realized_return, evaluated_at = evaluate_triple_barrier(
            entry_price, price_points, target_return, stop_return, horizon_end
        )
        if label == "UNRESOLVED":
            return None
        return label, realized_return, evaluated_at


def _daily_cutoffs(start_date: datetime, end_date: datetime) -> list[datetime]:
    cutoffs = []
    current = start_date
    while current <= end_date:
        cutoffs.append(current)
        current += timedelta(days=1)
    return cutoffs


def _assign_model_agreement(records: list[ModelMarketAssessmentRecord]) -> None:
    from collections import defaultdict

    from app.llm.assessment_agreement import compute_model_agreement

    by_asset: dict[str, list[str]] = defaultdict(list)
    for r in records:
        by_asset[r.asset_id].append(r.overall_assessment)
    agreement_by_asset = {asset_id: compute_model_agreement(v) for asset_id, v in by_asset.items()}
    for r in records:
        r.model_agreement = agreement_by_asset[r.asset_id]


def _hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_historical_series_fetcher(binance_client, coinbase_client, days: int):
    """Real fetcher: one call per asset (Binance primary, Coinbase fallback
    — same source-selection order 3b's live screening uses), covering the
    whole replay window's date range at once rather than per-replay-day."""

    def fetch(asset: Asset) -> HistoricalSeries | None:
        rows = binance_client.fetch_daily_ohlcv_with_timestamps(asset.symbol, days)
        source = "BINANCE"
        if rows is None:
            rows = coinbase_client.fetch_daily_ohlcv_with_timestamps(asset.symbol, days)
            source = "COINBASE"
        if not rows:
            return None
        dates = [r[0] for r in rows]
        closes = [r[1] for r in rows]
        volumes = [r[2] for r in rows]
        return HistoricalSeries(symbol=asset.symbol, asset_id=asset.id, source=source, dates=dates, closes=closes, volumes=volumes)

    return fetch


def make_funding_rate_fetcher(binance_client):
    """Real fetcher: Binance's genuinely historical funding-rate endpoint
    (verified live), one call per asset with a perpetual. Empty list (never
    fabricated) for assets without one."""

    def fetch(asset: Asset) -> list[dict]:
        try:
            return binance_client.fetch_historical_funding_rates(asset.symbol)
        except Exception as exc:
            logger.warning("Historical funding rate fetch failed for %s: %s", asset.symbol, exc)
            return []

    return fetch
