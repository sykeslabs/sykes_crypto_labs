import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.benchmarks.schemas import DecisionOutcome
from app.benchmarks.triple_barrier import compute_target_stop_thresholds
from app.config import Settings
from app.database.repository import (
    AdversarialResearchRepository,
    AssetRepository,
    AssetStatusRepository,
    DecisionOutcomeRepository,
    EvidenceObservationRepository,
    JudgeDecisionRepository,
    LLMAnalysisRepository,
    MarketRegimeRepository,
    ModelMarketAssessmentRepository,
    NewsRepository,
    PortfolioPositionRepository,
    PromptTemplateRepository,
    ScreenedUniverseRepository,
    SignalSourceRepository,
)
from app.judge.context import SYSTEM_PROMPT_TEMPLATE, build_judge_context, render_prompt
from app.judge.provider import OpenRouterJudgeProvider
from app.judge.schemas import JudgeDecisionRecord
from app.llm.cost import CostGuard

logger = logging.getLogger("crypto_ai_portfolio.judge")

PROMPT_TEMPLATE_NAME = "judge_decision"
PROMPT_TEMPLATE_STAGE = "3e"

# Per PHASE3E_PROMPT.md's non-negotiable: every decision_outcomes row created
# from this sub-phase's first live run onward is held out from future prompt/
# formula tuning — not a random subset, the boundary IS "3e went live." See
# README for the concrete first-live-run timestamp.
IN_HOLDOUT_WINDOW = True


@dataclass
class JudgeResult:
    decided_assets: list[str] = field(default_factory=list)
    stored: int = 0
    outcomes_created: int = 0
    failed: str | None = None
    skipped_cost_cap: bool = False
    estimated_cost: str | None = None
    decisions: list[JudgeDecisionRecord] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"decided={self.decided_assets} stored={self.stored} "
            f"outcomes_created={self.outcomes_created} failed={self.failed} "
            f"skipped_cost_cap={self.skipped_cost_cap}"
        )


class JudgeService:
    """3e: synthesizes 3b/3c/3d/Phase-2 evidence into one decision per
    candidate asset, persists the full narrative record to
    `judge_decisions`, and opens one `decision_outcomes` row per decision for
    the continuous calibration ledger."""

    def __init__(
        self,
        settings: Settings,
        asset_repo: AssetRepository,
        screened_universe_repo: ScreenedUniverseRepository,
        regime_repo: MarketRegimeRepository,
        evidence_repo: EvidenceObservationRepository,
        assessment_repo: ModelMarketAssessmentRepository,
        llm_analysis_repo: LLMAnalysisRepository,
        news_repo: NewsRepository,
        asset_status_repo: AssetStatusRepository,
        portfolio_position_repo: PortfolioPositionRepository,
        signal_source_repo: SignalSourceRepository,
        prompt_template_repo: PromptTemplateRepository,
        judge_decision_repo: JudgeDecisionRepository,
        decision_outcome_repo: DecisionOutcomeRepository,
        cost_guard: CostGuard,
        provider: OpenRouterJudgeProvider,
        adversarial_repo: AdversarialResearchRepository | None = None,
    ) -> None:
        self._settings = settings
        self._asset_repo = asset_repo
        self._screened_universe_repo = screened_universe_repo
        self._regime_repo = regime_repo
        self._evidence_repo = evidence_repo
        self._assessment_repo = assessment_repo
        self._llm_analysis_repo = llm_analysis_repo
        self._news_repo = news_repo
        self._asset_status_repo = asset_status_repo
        self._portfolio_position_repo = portfolio_position_repo
        self._signal_source_repo = signal_source_repo
        self._prompt_template_repo = prompt_template_repo
        self._judge_decision_repo = judge_decision_repo
        self._decision_outcome_repo = decision_outcome_repo
        self._cost_guard = cost_guard
        self._provider = provider
        self._adversarial_repo = adversarial_repo

    def run(self, run_id: str, current_allocations: dict[str, float] | None = None) -> JudgeResult:
        result = JudgeResult()

        candidates = self._screened_universe_repo.get_latest_top_candidates()
        if not candidates:
            logger.warning("No TOP_CANDIDATES found — run `--with-screening` before `--with-judge`.")
            return result

        active_assets = self._asset_repo.get_active_assets()
        assets_by_id = {a.id: a for a in active_assets}

        context = build_judge_context(
            run_id, self._settings, candidates, assets_by_id,
            self._regime_repo, self._evidence_repo, self._assessment_repo,
            self._llm_analysis_repo, self._news_repo, self._asset_status_repo,
            self._portfolio_position_repo, self._signal_source_repo,
            adversarial_repo=self._adversarial_repo,
            current_allocations=current_allocations,
        )
        if not context.assets:
            logger.warning(
                "No candidate has a 3d model assessment yet — run "
                "`--with-assessment` before `--with-judge`."
            )
            return result

        result.decided_assets = [ac.asset.symbol for ac in context.assets]

        allowed, reason = self._cost_guard.check()
        if not allowed:
            logger.warning("Skipping Judge: %s", reason)
            result.skipped_cost_cap = True
            return result

        system_prompt, user_prompt = render_prompt(context, self._settings.judge_prompt_version)
        prompt_template_id = self._prompt_template_repo.get_or_create(
            name=PROMPT_TEMPLATE_NAME,
            stage=PROMPT_TEMPLATE_STAGE,
            version=self._settings.judge_prompt_version,
            template_hash=hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest(),
        )

        provider_result = self._provider.decide(system_prompt, user_prompt)
        if provider_result.error is not None or provider_result.batch is None:
            logger.error("Judge (%s) failed: %s", self._provider.model, provider_result.error)
            result.failed = provider_result.error or "unknown error"
            return result

        result.estimated_cost = str(provider_result.estimated_cost)
        symbol_to_context = {ac.asset.symbol: ac for ac in context.assets}
        self._persist(run_id, provider_result, symbol_to_context, prompt_template_id, context.regime_id, result)

        logger.info("Judge complete: %s", result.summary)
        return result

    def _persist(self, run_id, provider_result, symbol_to_context, prompt_template_id, regime_id, result) -> None:
        items = provider_result.batch.decisions
        if not items:
            return

        per_item_cost = provider_result.estimated_cost / len(items)
        now = datetime.now(UTC)

        for item in items:
            ac = symbol_to_context.get(item.asset)
            if ac is None:
                logger.warning("Judge returned unknown asset symbol '%s' — skipping", item.asset)
                continue

            record = JudgeDecisionRecord(
                run_id=run_id,
                asset_id=ac.asset.id,
                created_at=now,
                decision=item.decision,
                confidence=item.confidence,
                target_allocation=item.target_allocation,
                expected_return=item.expected_return,
                expected_alpha=item.expected_alpha,
                risk_score=item.risk_score,
                uncertainty=item.uncertainty,
                model_agreement=item.model_agreement,
                source_agreement=item.source_agreement,
                investment_horizon_days=item.investment_horizon_days,
                key_evidence=item.key_evidence,
                contradictory_evidence=item.contradictory_evidence,
                key_risks=item.key_risks,
                invalidation_conditions=item.invalidation_conditions,
                requires_review=item.requires_review,
                thesis=item.thesis,
                macro_sensitivity=item.macro_sensitivity,
                regime_id=regime_id,
                prompt_template_id=prompt_template_id,
                estimated_cost=per_item_cost,
            )
            decision_id = self._judge_decision_repo.insert(record)
            record.id = decision_id
            result.decisions.append(record)
            result.stored += 1

            target_return, stop_return = compute_target_stop_thresholds(item.expected_return, item.risk_score)
            outcome = DecisionOutcome(
                decision_id=decision_id,
                asset_id=ac.asset.id,
                decision_timestamp=now,
                horizon_days=item.investment_horizon_days,
                target_return=target_return,
                stop_return=stop_return,
                outcome_label="UNRESOLVED",
                regime_at_decision=regime_id,
                judge_confidence=item.confidence,
                in_holdout_window=IN_HOLDOUT_WINDOW,
            )
            self._decision_outcome_repo.insert(outcome)
            result.outcomes_created += 1
