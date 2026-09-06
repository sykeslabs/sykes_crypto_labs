import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from app.config import Settings
from app.database.repository import (
    AdversarialResearchRepository,
    AssetRepository,
    EvidenceObservationRepository,
    MarketRegimeRepository,
    ModelMarketAssessmentRepository,
    PromptTemplateRepository,
    ScreenedUniverseRepository,
)
from app.llm.adversarial_context import (
    BEAR_SYSTEM_PROMPT_TEMPLATE,
    BULL_SYSTEM_PROMPT_TEMPLATE,
    SCENARIO_SYSTEM_PROMPT_TEMPLATE,
    build_research_context,
    compute_template_hash,
    render_bear_prompt,
    render_bull_prompt,
    render_scenario_prompt,
)
from app.llm.adversarial_schemas import AdversarialResearchRecord, BearBatch, BullBatch, ScenarioBatch
from app.llm.cost import CostGuard
from app.llm.structured_provider import OpenRouterStructuredProvider

logger = logging.getLogger("crypto_ai_portfolio.llm")

PROMPT_TEMPLATE_NAME = "adversarial_research"
PROMPT_TEMPLATE_STAGE = "3f"


@dataclass
class AdversarialResult:
    researched_assets: list[str] = field(default_factory=list)
    stored: int = 0
    failed: str | None = None
    skipped_cost_cap: bool = False
    estimated_cost: str | None = None
    # Per-stage cost, not just the summed total — bull/bear/scenario have
    # meaningfully different context sizes (scenario carries the most
    # accumulated context: bull + bear + its own reasoning), so cost sizing
    # (task 7) needs to see whether any one stage costs more than expected,
    # not just an averaged total that could hide it.
    bull_cost: str | None = None
    bear_cost: str | None = None
    scenario_cost: str | None = None

    @property
    def summary(self) -> str:
        return (
            f"researched={self.researched_assets} stored={self.stored} "
            f"failed={self.failed} skipped_cost_cap={self.skipped_cost_cap} "
            f"bull_cost=${self.bull_cost} bear_cost=${self.bear_cost} scenario_cost=${self.scenario_cost}"
        )


class AdversarialService:
    """3f: bull -> bear -> scenario research cycle over 3b's latest
    TOP_CANDIDATES, one call per stage (batched across every candidate,
    matching the cost-conscious pattern already used by 3d/3e), persisted
    to `adversarial_research`. The bull-rebuts-bear second pass (task 3's
    "where practical") is deliberately not built — kept to 3 calls to
    control cost, same trade-off logic as 3d deferring Grok."""

    def __init__(
        self,
        settings: Settings,
        asset_repo: AssetRepository,
        screened_universe_repo: ScreenedUniverseRepository,
        regime_repo: MarketRegimeRepository,
        evidence_repo: EvidenceObservationRepository,
        assessment_repo: ModelMarketAssessmentRepository,
        prompt_template_repo: PromptTemplateRepository,
        adversarial_repo: AdversarialResearchRepository,
        cost_guard: CostGuard,
        provider: OpenRouterStructuredProvider,
    ) -> None:
        self._settings = settings
        self._asset_repo = asset_repo
        self._screened_universe_repo = screened_universe_repo
        self._regime_repo = regime_repo
        self._evidence_repo = evidence_repo
        self._assessment_repo = assessment_repo
        self._prompt_template_repo = prompt_template_repo
        self._adversarial_repo = adversarial_repo
        self._cost_guard = cost_guard
        self._provider = provider

    def run(self, run_id: str) -> AdversarialResult:
        result = AdversarialResult()

        candidates = self._screened_universe_repo.get_latest_top_candidates()
        if not candidates:
            logger.warning("No TOP_CANDIDATES found — run `--with-screening` before `--with-adversarial`.")
            return result

        active_assets = self._asset_repo.get_active_assets()
        assets_by_id = {a.id: a for a in active_assets}

        context = build_research_context(
            run_id, candidates, assets_by_id, self._regime_repo, self._evidence_repo, self._assessment_repo,
        )
        if not context.assets:
            logger.warning("No candidate has a 3d model assessment yet — nothing to research.")
            return result
        result.researched_assets = [ac.asset.symbol for ac in context.assets]

        prompt_version = self._settings.adversarial_prompt_version
        prompt_template_id = self._prompt_template_repo.get_or_create(
            name=PROMPT_TEMPLATE_NAME, stage=PROMPT_TEMPLATE_STAGE, version=prompt_version,
            template_hash=compute_template_hash(
                BULL_SYSTEM_PROMPT_TEMPLATE, BEAR_SYSTEM_PROMPT_TEMPLATE, SCENARIO_SYSTEM_PROMPT_TEMPLATE
            ),
        )

        total_cost = Decimal("0")

        allowed, reason = self._cost_guard.check()
        if not allowed:
            logger.warning("Skipping adversarial research: %s", reason)
            result.skipped_cost_cap = True
            return result
        system_prompt, user_prompt = render_bull_prompt(context, prompt_version)
        bull_result = self._provider.call(system_prompt, user_prompt, BullBatch)
        total_cost += bull_result.estimated_cost
        result.bull_cost = str(bull_result.estimated_cost)
        if bull_result.error is not None or bull_result.parsed is None:
            result.failed = f"bull: {bull_result.error}"
            return result
        bull_batch: BullBatch = bull_result.parsed

        allowed, reason = self._cost_guard.check()
        if not allowed:
            logger.warning("Skipping adversarial research after bull stage: %s", reason)
            result.skipped_cost_cap = True
            return result
        system_prompt, user_prompt = render_bear_prompt(context, bull_batch, prompt_version)
        bear_result = self._provider.call(system_prompt, user_prompt, BearBatch)
        total_cost += bear_result.estimated_cost
        result.bear_cost = str(bear_result.estimated_cost)
        if bear_result.error is not None or bear_result.parsed is None:
            result.failed = f"bear: {bear_result.error}"
            return result
        bear_batch: BearBatch = bear_result.parsed

        allowed, reason = self._cost_guard.check()
        if not allowed:
            logger.warning("Skipping adversarial research after bear stage: %s", reason)
            result.skipped_cost_cap = True
            return result
        system_prompt, user_prompt = render_scenario_prompt(context, bull_batch, bear_batch, prompt_version)
        scenario_result = self._provider.call(system_prompt, user_prompt, ScenarioBatch)
        total_cost += scenario_result.estimated_cost
        result.scenario_cost = str(scenario_result.estimated_cost)
        if scenario_result.error is not None or scenario_result.parsed is None:
            result.failed = f"scenario: {scenario_result.error}"
            return result
        scenario_batch: ScenarioBatch = scenario_result.parsed

        result.estimated_cost = str(total_cost)
        symbol_to_asset = {ac.asset.symbol: ac.asset for ac in context.assets}
        bull_by_asset = {c.asset: c for c in bull_batch.cases}
        bear_by_asset = {c.asset: c for c in bear_batch.cases}
        scenario_by_asset = {s.asset: s for s in scenario_batch.scenarios}

        symbols_with_all_three = set(bull_by_asset) & set(bear_by_asset) & set(scenario_by_asset)
        per_item_cost = total_cost / len(symbols_with_all_three) if symbols_with_all_three else Decimal("0")
        now = datetime.now(UTC)

        for symbol in symbols_with_all_three:
            asset = symbol_to_asset.get(symbol)
            if asset is None:
                continue
            record = AdversarialResearchRecord(
                run_id=run_id, asset_id=asset.id, prompt_template_id=prompt_template_id,
                bull_case=bull_by_asset[symbol].model_dump(),
                bear_case=bear_by_asset[symbol].model_dump(),
                bull_rebuttal=None,
                scenarios=scenario_by_asset[symbol].model_dump(),
                estimated_cost=per_item_cost, created_at=now,
            )
            self._adversarial_repo.insert(record)
            result.stored += 1

        logger.info("Adversarial research complete: %s cost=$%s", result.summary, total_cost)
        return result
