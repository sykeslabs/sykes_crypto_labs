import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from app.config import Settings
from app.database.repository import (
    AssetRepository,
    AssetStatusRepository,
    EvidenceObservationRepository,
    MarketRegimeRepository,
    MarketSnapshotRepository,
    ModelMarketAssessmentRepository,
    NewsRepository,
    PromptTemplateRepository,
    ScreenedUniverseRepository,
)
from app.llm.assessment_agreement import compute_model_agreement
from app.llm.assessment_context import (
    SYSTEM_PROMPT_TEMPLATE,
    build_assessment_context,
    render_prompt,
)
from app.llm.assessment_provider import OpenRouterAssessmentProvider
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.llm.cost import CostGuard

logger = logging.getLogger("crypto_ai_portfolio.llm")

PROMPT_TEMPLATE_NAME = "market_assessment"
PROMPT_TEMPLATE_STAGE = "3d"


@dataclass
class AssessmentResult:
    stored_by_provider: dict[str, int] = field(default_factory=dict)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped_cost_cap: list[str] = field(default_factory=list)
    assessed_assets: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"assessed={self.assessed_assets} "
            f"stored={self.stored_by_provider} "
            f"failed={[p for p, _ in self.failed]} "
            f"skipped_cost_cap={self.skipped_cost_cap}"
        )


class AssessmentService:
    """3d: multi-model current market assessment over 3b's latest
    TOP_CANDIDATES, sharing one market-regime snapshot and one rendered
    context across every configured provider. A new, parallel evidence type
    — does not touch or replace Phase 2's `llm_analyses`/`LLMResearchService`."""

    def __init__(
        self,
        settings: Settings,
        asset_repo: AssetRepository,
        screened_universe_repo: ScreenedUniverseRepository,
        regime_repo: MarketRegimeRepository,
        evidence_repo: EvidenceObservationRepository,
        news_repo: NewsRepository,
        asset_status_repo: AssetStatusRepository,
        snapshot_repo: MarketSnapshotRepository,
        prompt_template_repo: PromptTemplateRepository,
        assessment_repo: ModelMarketAssessmentRepository,
        cost_guard: CostGuard,
        providers: list[OpenRouterAssessmentProvider],
    ) -> None:
        self._settings = settings
        self._asset_repo = asset_repo
        self._screened_universe_repo = screened_universe_repo
        self._regime_repo = regime_repo
        self._evidence_repo = evidence_repo
        self._news_repo = news_repo
        self._asset_status_repo = asset_status_repo
        self._snapshot_repo = snapshot_repo
        self._prompt_template_repo = prompt_template_repo
        self._assessment_repo = assessment_repo
        self._cost_guard = cost_guard
        self._providers = providers

    def run(self, run_id: str) -> AssessmentResult:
        result = AssessmentResult()

        candidates = self._screened_universe_repo.get_latest_top_candidates()
        if not candidates:
            logger.warning(
                "No TOP_CANDIDATES found — run `--with-screening` at least "
                "once before `--with-assessment`."
            )
            return result

        active_assets = self._asset_repo.get_active_assets()
        assets_by_id = {a.id: a for a in active_assets}

        context = build_assessment_context(
            run_id, self._settings, candidates, assets_by_id,
            self._snapshot_repo, self._regime_repo, self._evidence_repo,
            self._news_repo, self._asset_status_repo,
        )
        if not context.assets:
            logger.warning("No valid assets resolved from TOP_CANDIDATES — nothing to assess.")
            return result

        result.assessed_assets = [ac.asset.symbol for ac in context.assets]
        system_prompt, user_prompt = render_prompt(context, self._settings.assessment_prompt_version)
        prompt_template_id = self._prompt_template_repo.get_or_create(
            name=PROMPT_TEMPLATE_NAME,
            stage=PROMPT_TEMPLATE_STAGE,
            version=self._settings.assessment_prompt_version,
            template_hash=hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest(),
        )
        symbol_to_asset = {ac.asset.symbol: ac.asset for ac in context.assets}

        provider_results = {}
        for provider in self._providers:
            allowed, reason = self._cost_guard.check()
            if not allowed:
                logger.warning("Skipping %s: %s", provider.name, reason)
                result.skipped_cost_cap.append(provider.name)
                continue

            provider_result = provider.analyze(system_prompt, user_prompt)
            if provider_result.error is not None or provider_result.batch is None:
                logger.error("%s (%s) failed: %s", provider.name, provider.model, provider_result.error)
                result.failed.append((provider.name, provider_result.error or "unknown error"))
                continue

            provider_results[provider.name] = provider_result

        agreement_by_symbol = _compute_agreement_by_symbol(provider_results)

        for provider_name, provider_result in provider_results.items():
            stored = self._persist(
                run_id, provider_result, symbol_to_asset, prompt_template_id,
                context.as_of, agreement_by_symbol,
            )
            result.stored_by_provider[provider_name] = stored
            logger.info(
                "%s (%s): stored %d assessments, cost=$%s",
                provider_name, provider_result.model, stored, provider_result.estimated_cost,
            )

        logger.info("Assessment complete: %s", result.summary)
        return result

    def _persist(
        self, run_id, provider_result, symbol_to_asset, prompt_template_id,
        data_cutoff_timestamp, agreement_by_symbol,
    ) -> int:
        assessments = provider_result.batch.assessments
        if not assessments:
            return 0

        # One call covers every candidate; split its cost evenly across the
        # resulting rows (same pattern as Phase 2's LLMResearchService).
        per_item_cost = provider_result.estimated_cost / len(assessments)
        stored = 0

        for item in assessments:
            asset = symbol_to_asset.get(item.asset)
            if asset is None:
                logger.warning(
                    "%s returned unknown asset symbol '%s' — skipping",
                    provider_result.provider, item.asset,
                )
                continue

            record = ModelMarketAssessmentRecord(
                run_id=run_id,
                asset_id=asset.id,
                provider=provider_result.provider,
                model=provider_result.model,
                prompt_template_id=prompt_template_id,
                assessment_timestamp=item.assessment_timestamp,
                data_cutoff_timestamp=data_cutoff_timestamp,
                short_term_direction=item.direction.short_term,
                medium_term_direction=item.direction.medium_term,
                long_term_direction=item.direction.long_term,
                short_term_confidence=item.confidence.short_term,
                medium_term_confidence=item.confidence.medium_term,
                long_term_confidence=item.confidence.long_term,
                expected_return_7d=item.expected_return.return_7d,
                expected_return_30d=item.expected_return.return_30d,
                expected_return_90d=item.expected_return.return_90d,
                risk_score=item.risk.score,
                risk_level=item.risk.level,
                market_regime=item.market_regime,
                model_agreement=agreement_by_symbol.get(item.asset, 1.0),
                overall_assessment=item.overall_assessment,
                thesis=item.thesis,
                # This asset's own slice, not the whole batch response — one
                # call covers every candidate, so storing the full raw
                # response on each row would duplicate it N times (same fix
                # applied to Phase 2's LLMResearchService).
                key_drivers=[d.model_dump() for d in item.key_drivers],
                key_risks=[d.model_dump() for d in item.key_risks],
                source_assessment=[d.model_dump() for d in item.source_assessment],
                invalidation_conditions=item.invalidation_conditions,
                raw_response=item.model_dump(mode="json"),
                estimated_cost=per_item_cost,
            )
            self._assessment_repo.insert(record)
            stored += 1

        return stored


def _compute_agreement_by_symbol(provider_results: dict) -> dict[str, float]:
    directions_by_symbol: dict[str, list[str]] = defaultdict(list)
    for provider_result in provider_results.values():
        for item in provider_result.batch.assessments:
            directions_by_symbol[item.asset].append(item.overall_assessment)
    return {
        symbol: compute_model_agreement(directions)
        for symbol, directions in directions_by_symbol.items()
    }
