import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import Settings
from app.database.repository import AssetRepository, LLMAnalysisRepository, MarketSnapshotRepository, NewsRepository
from app.llm.cost import CostGuard
from app.llm.provider import LLMProvider
from app.llm.research_context import build_research_context, compute_input_hash, render_prompt
from app.llm.schemas import LLMAnalysisRecord

logger = logging.getLogger("crypto_ai_portfolio.llm")


@dataclass
class LLMResearchResult:
    stored_by_provider: dict[str, int] = field(default_factory=dict)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped_cost_cap: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"stored={self.stored_by_provider} "
            f"failed={[p for p, _ in self.failed]} "
            f"skipped_cost_cap={self.skipped_cost_cap}"
        )


class LLMResearchService:
    """Builds one shared research context, sends it to every configured
    provider, and persists each valid (provider, asset) analysis. One
    provider failing (cost cap, API error, malformed output) never blocks
    the others."""

    def __init__(
        self,
        settings: Settings,
        asset_repo: AssetRepository,
        snapshot_repo: MarketSnapshotRepository,
        news_repo: NewsRepository,
        llm_repo: LLMAnalysisRepository,
        cost_guard: CostGuard,
        providers: list[LLMProvider],
    ) -> None:
        self._settings = settings
        self._asset_repo = asset_repo
        self._snapshot_repo = snapshot_repo
        self._news_repo = news_repo
        self._llm_repo = llm_repo
        self._cost_guard = cost_guard
        self._providers = providers

    def run(self, run_id: str) -> LLMResearchResult:
        result = LLMResearchResult()

        assets = self._asset_repo.get_active_assets()
        if not assets:
            logger.warning("No active assets found — skipping LLM research.")
            return result

        context = build_research_context(
            run_id, self._settings, assets, self._snapshot_repo, self._news_repo
        )
        system_prompt, user_prompt = render_prompt(context, self._settings.prompt_version)
        input_hash = compute_input_hash(system_prompt, user_prompt)
        symbol_to_asset = {a.symbol: a for a in assets}

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

            stored = self._persist(
                run_id, provider_result, symbol_to_asset, input_hash
            )
            result.stored_by_provider[provider.name] = stored
            logger.info(
                "%s (%s): stored %d analyses, cost=$%s",
                provider.name, provider.model, stored, provider_result.estimated_cost,
            )

        logger.info("LLM research complete: %s", result.summary)
        return result

    def _persist(self, run_id, provider_result, symbol_to_asset, input_hash) -> int:
        analyses = provider_result.batch.analyses
        if not analyses:
            return 0

        # The single API call covers every asset; split its cost evenly across
        # the resulting rows so per-row cost is meaningful while the sum across
        # a provider's rows for this run still equals the true call cost.
        per_item_cost = provider_result.estimated_cost / len(analyses)
        timestamp = datetime.now(UTC)
        stored = 0

        for item in analyses:
            asset = symbol_to_asset.get(item.asset_symbol)
            if asset is None:
                logger.warning(
                    "%s returned unknown asset symbol '%s' — skipping",
                    provider_result.provider, item.asset_symbol,
                )
                continue

            record = LLMAnalysisRecord(
                run_id=run_id,
                asset_id=asset.id,
                provider=provider_result.provider,
                model=provider_result.model,
                prompt_version=self._settings.prompt_version,
                timestamp=timestamp,
                input_hash=input_hash,
                # This asset's own slice of the batch response, not the whole
                # provider payload — one call covers every asset, so storing
                # the full raw response on each row would duplicate it N
                # times (against the "don't store raw responses unnecessarily"
                # cost guidance). The full raw response is still logged for
                # this run, just not persisted per row.
                response=item.model_dump(),
                action=item.action,
                confidence=item.confidence,
                target_allocation=item.target_allocation,
                investment_horizon=item.investment_horizon,
                bull_case=item.bull_case,
                bear_case=item.bear_case,
                catalysts=item.catalysts,
                risks=item.risks,
                invalidation_conditions=item.invalidation_conditions,
                token_usage=provider_result.token_usage,
                estimated_cost=per_item_cost,
            )
            self._llm_repo.insert_analysis(record)
            stored += 1

        return stored
