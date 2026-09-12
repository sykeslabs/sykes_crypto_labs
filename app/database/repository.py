from datetime import UTC, datetime

from supabase import Client

from app.benchmarks.schemas import (
    CalibrationRunRecord,
    DecisionOutcome,
    EvidenceValueReportRecord,
    JudgeReasoningAuditRecord,
)
from app.database.models import Asset, AssetStatusHistory, AssetStatusValue, SignalSource
from app.judge.schemas import JudgeDecisionRecord
from app.llm.adversarial_schemas import AdversarialResearchRecord
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.llm.schemas import LLMAnalysisRecord
from app.market_data.evidence_schemas import EvidenceObservation
from app.market_data.schemas import MarketSnapshot
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset
from app.news.schemas import NewsArticle
from app.portfolio.schemas import HoldingsLedgerEntry, PortfolioAllocationChange, PortfolioPosition


class AssetRepository:
    """Reads/writes the configurable asset universe in the `assets` table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_active_assets(self) -> list[Asset]:
        response = (
            self._client.table("assets")
            .select("*")
            .eq("active", True)
            .execute()
        )
        return [Asset.model_validate(row) for row in response.data]

    def get_by_coingecko_id(self, coingecko_id: str) -> Asset | None:
        response = (
            self._client.table("assets")
            .select("*")
            .eq("coingecko_id", coingecko_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return Asset.model_validate(response.data[0])

    def get_by_id(self, asset_id: str) -> Asset | None:
        """Phase 5a: existence check for a holdings-ledger entry — an
        asset need only be tracked (any status), not `active`, per that
        sub-phase's own validation rule."""
        response = self._client.table("assets").select("*").eq("id", asset_id).limit(1).execute()
        if not response.data:
            return None
        return Asset.model_validate(response.data[0])

    def get_by_symbol(self, symbol: str) -> Asset | None:
        """Phase 5b: lets a holdings-ledger entry be made by real token
        symbol (e.g. "SOL") instead of a raw asset UUID — same "any
        status, not just active" rule as `get_by_id`. Case-insensitive
        (`ilike`) so "sol"/"Sol"/"SOL" all resolve the same real asset."""
        response = self._client.table("assets").select("*").ilike("symbol", symbol).limit(1).execute()
        if not response.data:
            return None
        return Asset.model_validate(response.data[0])

    def create_asset(
        self,
        symbol: str,
        name: str,
        coingecko_id: str,
        coinmarketcap_id: str | None = None,
        active: bool = True,
        in_asset: bool = False,
    ) -> Asset:
        """Inserts a new asset — used when 3b's screening surfaces a
        genuinely new candidate not already in the universe."""
        response = (
            self._client.table("assets")
            .insert(
                {
                    "symbol": symbol,
                    "name": name,
                    "coingecko_id": coingecko_id,
                    "coinmarketcap_id": coinmarketcap_id,
                    "active": active,
                    "in_asset": in_asset,
                }
            )
            .execute()
        )
        return Asset.model_validate(response.data[0])


class MarketSnapshotRepository:
    """Persists market snapshots, deduplicating on write."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_latest_snapshot_timestamp(self, asset_id: str) -> datetime | None:
        response = (
            self._client.table("market_snapshots")
            .select("timestamp")
            .eq("asset_id", asset_id)
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return datetime.fromisoformat(response.data[0]["timestamp"])

    def get_latest_snapshot(self, asset_id: str) -> MarketSnapshot | None:
        response = (
            self._client.table("market_snapshots")
            .select("*")
            .eq("asset_id", asset_id)
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return MarketSnapshot.model_validate(response.data[0])

    def get_recent_snapshots(self, asset_id: str, limit: int = 10) -> list[MarketSnapshot]:
        """Most recent snapshots for an asset, newest first — used by 3d's
        pre-context sanity check (a bad-tick outlier check against the
        asset's own recent readings, same z-score/pct-jump idea as 3b's
        anomaly flag, applied here to Phase 1's own stored history)."""
        response = (
            self._client.table("market_snapshots")
            .select("*")
            .eq("asset_id", asset_id)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return [MarketSnapshot.model_validate(row) for row in response.data]

    def insert_snapshot(self, snapshot: MarketSnapshot) -> None:
        self._client.table("market_snapshots").insert(snapshot.to_row()).execute()

    def get_snapshots_in_range(
        self, asset_id: str, start: datetime, end: datetime
    ) -> list[MarketSnapshot]:
        """Oldest-first snapshots in [start, end] — used by 3e's outcome
        evaluation (triple-barrier walk-forward) and by the Risk Engine's
        correlation check (return series from actual stored history)."""
        response = (
            self._client.table("market_snapshots")
            .select("*")
            .eq("asset_id", asset_id)
            .gte("timestamp", start.isoformat())
            .lte("timestamp", end.isoformat())
            .order("timestamp", desc=False)
            .execute()
        )
        return [MarketSnapshot.model_validate(row) for row in response.data]


class NewsRepository:
    """Persists news articles, deduplicating on `content_hash`."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_existing_hashes(self, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        response = (
            self._client.table("news")
            .select("content_hash")
            .in_("content_hash", hashes)
            .execute()
        )
        return {row["content_hash"] for row in response.data}

    def insert_articles(self, articles: list[NewsArticle]) -> None:
        if not articles:
            return
        self._client.table("news").insert([a.to_row() for a in articles]).execute()

    def get_recent_relevant_news(
        self, symbols: list[str], since: datetime, until: datetime, limit_per_asset: int
    ) -> dict[str, list[NewsArticle]]:
        """Returns up to `limit_per_asset` recent articles per symbol, published
        in [since, until] — `until` enforces the no-lookahead rule for a given run.
        """
        if not symbols:
            return {}

        response = (
            self._client.table("news")
            .select("*")
            .overlaps("relevant_assets", symbols)
            .gte("published_at", since.isoformat())
            .lte("published_at", until.isoformat())
            .order("published_at", desc=True)
            .execute()
        )

        by_symbol: dict[str, list[NewsArticle]] = {symbol: [] for symbol in symbols}
        for row in response.data:
            article = NewsArticle.model_validate(row)
            for symbol in article.relevant_assets:
                if symbol in by_symbol and len(by_symbol[symbol]) < limit_per_asset:
                    by_symbol[symbol].append(article)
        return by_symbol


class LLMAnalysisRepository:
    """Persists LLM research output and supports the cost-guard's spend queries."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert_analysis(self, record: LLMAnalysisRecord) -> None:
        self._client.table("llm_analyses").insert(record.to_row()).execute()

    def get_latest_by_asset(self, asset_id: str, limit: int = 3) -> list[LLMAnalysisRecord]:
        """Most recent Phase 2 analyses for one asset across providers — one
        of the Judge's (3e) inputs, alongside 3d's richer multi-horizon
        assessment."""
        response = (
            self._client.table("llm_analyses")
            .select("*")
            .eq("asset_id", asset_id)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return [LLMAnalysisRecord.model_validate(row) for row in response.data]

    def get_latest_by_asset_as_of(self, asset_id: str, as_of: datetime, limit: int = 3) -> list[LLMAnalysisRecord]:
        """Point-in-time-safe version of `get_latest_by_asset` — used by
        3e.1's replay so a backfilled decision only sees Phase 2 analyses
        that genuinely existed by that historical date, never today's."""
        response = (
            self._client.table("llm_analyses")
            .select("*")
            .eq("asset_id", asset_id)
            .lte("timestamp", as_of.isoformat())
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return [LLMAnalysisRecord.model_validate(row) for row in response.data]

    def get_recent(self, limit: int | None = None) -> list[LLMAnalysisRecord]:
        """Phase 5b addendum: recent Phase 2 research analyses across every
        asset and provider, newest first -- the dashboard's own "LLM
        answers" feed (this table had no cross-asset read method before,
        only `get_latest_by_asset`). `limit=None` (default) returns every
        analysis ever made, matching `/news/recent` and
        `/judge/decisions/recent`'s same "None means unlimited" convention."""
        query = self._client.table("llm_analyses").select("*").order("timestamp", desc=True)
        if limit is not None:
            query = query.limit(limit)
        response = query.execute()
        return [LLMAnalysisRecord.model_validate(row) for row in response.data]


class AssetStatusRepository:
    """Reads/writes `asset_status_history` — an append-only record of
    HELD/WATCHLIST/CANDIDATE/REJECTED transitions. `assets.active`/
    `assets.in_asset` are separate and untouched by this."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_latest_status(self, asset_id: str) -> AssetStatusHistory | None:
        response = (
            self._client.table("asset_status_history")
            .select("*")
            .eq("asset_id", asset_id)
            .order("changed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return AssetStatusHistory.model_validate(response.data[0])

    def get_latest_status_as_of(self, asset_id: str, as_of: datetime) -> AssetStatusHistory | None:
        """Point-in-time-safe version of `get_latest_status` — used by 3e.1's
        replay so a backfilled decision only sees status changes that had
        genuinely happened by that historical date."""
        response = (
            self._client.table("asset_status_history")
            .select("*")
            .eq("asset_id", asset_id)
            .lte("changed_at", as_of.isoformat())
            .order("changed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return AssetStatusHistory.model_validate(response.data[0])

    def record_status_change(
        self, asset_id: str, status: AssetStatusValue, reason: str | None = None
    ) -> None:
        entry = AssetStatusHistory(
            asset_id=asset_id, status=status, reason=reason, changed_at=datetime.now(UTC)
        )
        self._client.table("asset_status_history").insert(entry.to_row()).execute()


class SignalSourceRepository:
    """Reads the `signal_sources` registry — which evidence sources exist
    and their current status."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_all(self) -> list[SignalSource]:
        response = self._client.table("signal_sources").select("*").execute()
        return [SignalSource.model_validate(row) for row in response.data]

    def get(self, name: str) -> SignalSource | None:
        response = (
            self._client.table("signal_sources").select("*").eq("name", name).limit(1).execute()
        )
        if not response.data:
            return None
        return SignalSource.model_validate(response.data[0])

    def update_status(self, name: str, status: str, notes: str | None = None) -> None:
        payload = {"status": status, "last_checked_at": datetime.now(UTC).isoformat()}
        if notes is not None:
            payload["notes"] = notes
        self._client.table("signal_sources").update(payload).eq("name", name).execute()


class ScreenedUniverseRepository:
    """Persists the full screened universe for a run (task 9) — one row per
    screened asset, not just TOP_CANDIDATES, so later validation work can
    check for survivorship bias in discovery."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert_many(self, rows: list[ScreenedAsset]) -> None:
        if not rows:
            return
        self._client.table("screened_universe").insert([r.to_row() for r in rows]).execute()

    def get_latest_volatility(self, symbol: str) -> float | None:
        """Most recent `volatility_30d` computed for `symbol` by 3b's
        screening — used by 3c's VRP computation (implied vs. realized)."""
        response = (
            self._client.table("screened_universe")
            .select("volatility_30d")
            .eq("symbol", symbol)
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data or response.data[0]["volatility_30d"] is None:
            return None
        return float(response.data[0]["volatility_30d"])

    def get_latest_for_symbol(self, symbol: str) -> ScreenedAsset | None:
        response = (
            self._client.table("screened_universe")
            .select("*")
            .eq("symbol", symbol)
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return ScreenedAsset.model_validate(response.data[0])

    def get_latest_top_candidates(self) -> list[ScreenedAsset]:
        """All TOP_CANDIDATE rows from the most recent screening run that
        had any — used by 3d as the assessment target list. Empty if
        `--with-screening` has never been run."""
        latest = (
            self._client.table("screened_universe")
            .select("run_id, computed_at")
            .eq("is_top_candidate", True)
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not latest.data:
            return []

        run_id = latest.data[0]["run_id"]
        response = (
            self._client.table("screened_universe")
            .select("*")
            .eq("run_id", run_id)
            .eq("is_top_candidate", True)
            .execute()
        )
        return [ScreenedAsset.model_validate(row) for row in response.data]

    def get_latest_full_universe(self) -> list[ScreenedAsset]:
        """Phase 5: every screened asset (not just TOP_CANDIDATES) from the
        most recent screening run — the dashboard's full-universe view."""
        latest = (
            self._client.table("screened_universe")
            .select("run_id, computed_at")
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not latest.data:
            return []

        run_id = latest.data[0]["run_id"]
        response = (
            self._client.table("screened_universe")
            .select("*")
            .eq("run_id", run_id)
            .execute()
        )
        return [ScreenedAsset.model_validate(row) for row in response.data]


class MarketRegimeRepository:
    """Persists/reads `market_regime_snapshots` — the one regime label per
    run every downstream stage (3d, 3e) reads instead of inferring its own."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, snapshot: MarketRegimeSnapshot) -> None:
        self._client.table("market_regime_snapshots").insert(snapshot.to_row()).execute()

    def get_latest(self) -> MarketRegimeSnapshot | None:
        response = (
            self._client.table("market_regime_snapshots")
            .select("*")
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return MarketRegimeSnapshot.model_validate(response.data[0])

    def get_by_id(self, regime_id: str) -> MarketRegimeSnapshot | None:
        """Phase 5b: resolves a `decision_outcomes.regime_at_decision` FK
        (a raw UUID) to its real `regime` label (e.g. "RISK_ON") -- that
        column stores the snapshot id, never the label itself, a real gap
        found live when the dashboard first rendered a raw UUID."""
        response = (
            self._client.table("market_regime_snapshots")
            .select("*")
            .eq("id", regime_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return MarketRegimeSnapshot.model_validate(response.data[0])


class EvidenceObservationRepository:
    """Persists/reads `evidence_observations` — the shared 3a
    evidence-provenance shape reused by every 3c/3f source."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, observation: EvidenceObservation) -> None:
        self._client.table("evidence_observations").insert(observation.to_row()).execute()

    def insert_many(self, observations: list[EvidenceObservation]) -> None:
        if not observations:
            return
        self._client.table("evidence_observations").insert(
            [o.to_row() for o in observations]
        ).execute()

    def get_latest_value_as_of(
        self, source: str, asset_id: str | None, as_of: datetime
    ) -> EvidenceObservation | None:
        """The "value as known at time T" query from 3a: latest row by
        `retrieval_timestamp` where `retrieval_timestamp <= as_of`."""
        query = (
            self._client.table("evidence_observations")
            .select("*")
            .eq("source", source)
            .lte("retrieval_timestamp", as_of.isoformat())
            .order("retrieval_timestamp", desc=True)
            .limit(1)
        )
        query = query.eq("asset_id", asset_id) if asset_id else query.is_("asset_id", "null")
        response = query.execute()
        if not response.data:
            return None
        return EvidenceObservation.model_validate(response.data[0])

    def get_latest_by_asset(self, asset_id: str, limit: int = 150) -> list[EvidenceObservation]:
        """Recent observations for one asset across every 3c/3f source.
        Callers dedupe single-value sources by `source` name (first/latest
        occurrence wins); a `MULTI_ENTRY_ASSET_SOURCES` source (e.g. dated-
        futures term structure) is instead grouped by `(source, timeframe)`
        via `group_observations_by_multi_entry_source` — see
        app/database/evidence_provenance.py. limit=150, not 50: a single
        multi-entry source can emit >12 rows per asset per run
        (deribit_futures_term_structure's dated instruments), and 50 risked
        silently truncating older single-value readings once multi-entry
        rows accumulated across a few runs (verified live)."""
        response = (
            self._client.table("evidence_observations")
            .select("*")
            .eq("asset_id", asset_id)
            .order("retrieval_timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return [EvidenceObservation.model_validate(row) for row in response.data]

    def get_latest_global(self, source: str, limit: int = 10) -> list[EvidenceObservation]:
        """Recent GLOBAL_CRYPTO/MACRO-scope observations (asset_id is null)
        for one source, e.g. `defillama_stablecoin_supply`."""
        response = (
            self._client.table("evidence_observations")
            .select("*")
            .is_("asset_id", "null")
            .eq("source", source)
            .order("retrieval_timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return [EvidenceObservation.model_validate(row) for row in response.data]

    def get_latest_global_all(self, limit: int = 100) -> list[EvidenceObservation]:
        """Recent GLOBAL_CRYPTO/MACRO-scope observations across EVERY
        source (asset_id is null) — used by 3f's Judge context, which needs
        to show the shared macro/liquidity/regulatory-calendar backdrop
        without knowing every source name in advance. Callers dedupe by
        `source` (first/latest occurrence wins), same convention as
        `get_latest_by_asset`."""
        response = (
            self._client.table("evidence_observations")
            .select("*")
            .is_("asset_id", "null")
            .order("retrieval_timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return [EvidenceObservation.model_validate(row) for row in response.data]


class PromptTemplateRepository:
    """Reads/writes `prompt_templates` (3a schema, populated starting 3d)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_or_create(self, name: str, stage: str, version: str, template_hash: str) -> str:
        """Returns the id of the (name, stage, version) template, inserting
        it if this exact version hasn't been recorded yet."""
        existing = (
            self._client.table("prompt_templates")
            .select("id")
            .eq("name", name)
            .eq("stage", stage)
            .eq("version", version)
            .limit(1)
            .execute()
        )
        if existing.data:
            return existing.data[0]["id"]

        inserted = (
            self._client.table("prompt_templates")
            .insert({"name": name, "stage": stage, "version": version, "template_hash": template_hash})
            .execute()
        )
        return inserted.data[0]["id"]


class ModelMarketAssessmentRepository:
    """Persists `model_market_assessments` (3d) — a new, parallel evidence
    type, distinct from Phase 2's `llm_analyses`."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, record: ModelMarketAssessmentRecord) -> None:
        self._client.table("model_market_assessments").insert(record.to_row()).execute()

    def get_latest_by_asset(self, asset_id: str, limit: int = 10) -> list[ModelMarketAssessmentRecord]:
        """Recent assessments for one asset across every model — used by
        3e's Judge context alongside `get_latest_run_assessments()` when the
        caller already knows the asset it wants (kept separate rather than
        always filtering the full-run fetch, mirroring the
        EvidenceObservationRepository per-asset/global split)."""
        response = (
            self._client.table("model_market_assessments")
            .select("*")
            .eq("asset_id", asset_id)
            .order("assessment_timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        return [ModelMarketAssessmentRecord.model_validate(row) for row in response.data]

    def get_latest_run_assessments(self) -> list[ModelMarketAssessmentRecord]:
        """Every row from the most recent run that produced any assessments
        — same two-step "latest run_id, then all its rows" pattern as
        `ScreenedUniverseRepository.get_latest_top_candidates()`. Used by
        3e's Judge so it can run decoupled from whether `--with-assessment`
        happened earlier in the *same* process invocation."""
        latest = (
            self._client.table("model_market_assessments")
            .select("run_id, assessment_timestamp")
            .order("assessment_timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if not latest.data:
            return []

        run_id = latest.data[0]["run_id"]
        response = (
            self._client.table("model_market_assessments")
            .select("*")
            .eq("run_id", run_id)
            .execute()
        )
        return [ModelMarketAssessmentRecord.model_validate(row) for row in response.data]


class JudgeDecisionRepository:
    """Persists/reads `judge_decisions` (3a schema, populated starting 3e) —
    the full narrative record of every Judge output."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, record: JudgeDecisionRecord) -> str:
        response = self._client.table("judge_decisions").insert(record.to_row()).execute()
        return response.data[0]["id"]

    def get_latest_by_asset(self, asset_id: str) -> JudgeDecisionRecord | None:
        response = (
            self._client.table("judge_decisions")
            .select("*")
            .eq("asset_id", asset_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return JudgeDecisionRecord.model_validate(response.data[0])

    def get_recent(self, limit: int | None = 50, is_backfilled: bool | None = None) -> list[JudgeDecisionRecord]:
        """Phase 5: recent decisions across every asset, newest first — the
        dashboard's decisions feed. `is_backfilled` optionally filters to
        just backfilled or just live rows (never mixes them silently).
        `limit=None` (Phase 5b addendum) returns every decision ever made,
        not just a capped slice -- no `.limit()` call at all in that case,
        matching `/news/recent`'s same "None means unlimited" convention."""
        query = self._client.table("judge_decisions").select("*")
        if is_backfilled is not None:
            query = query.eq("is_backfilled", is_backfilled)
        query = query.order("created_at", desc=True)
        if limit is not None:
            query = query.limit(limit)
        response = query.execute()
        return [JudgeDecisionRecord.model_validate(row) for row in response.data]

    def get_by_id(self, decision_id: str) -> JudgeDecisionRecord | None:
        response = self._client.table("judge_decisions").select("*").eq("id", decision_id).limit(1).execute()
        if not response.data:
            return None
        return JudgeDecisionRecord.model_validate(response.data[0])


class DecisionOutcomeRepository:
    """Persists/reads `decision_outcomes` (3a schema) — the continuous
    calibration ledger the evaluation step and calibration script both read
    from."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, outcome: DecisionOutcome) -> None:
        self._client.table("decision_outcomes").insert(outcome.to_row()).execute()

    def get_unresolved(self, limit: int = 500) -> list[DecisionOutcome]:
        response = (
            self._client.table("decision_outcomes")
            .select("*")
            .eq("outcome_label", "UNRESOLVED")
            .limit(limit)
            .execute()
        )
        return [DecisionOutcome.model_validate(row) for row in response.data]

    def update_outcome(
        self, decision_id: str, realized_return: float, outcome_label: str, evaluated_at: datetime
    ) -> None:
        self._client.table("decision_outcomes").update(
            {
                "realized_return": realized_return,
                "outcome_label": outcome_label,
                "evaluated_at": evaluated_at.isoformat(),
            }
        ).eq("decision_id", decision_id).execute()

    def get_resolved_without_net_of_costs(self, limit: int = 500) -> list[DecisionOutcome]:
        """Phase 4 task 2: resolved rows still missing a net-of-costs
        figure — lets `scripts/apply_execution_costs.py` be re-run safely
        without recomputing already-processed rows."""
        response = (
            self._client.table("decision_outcomes")
            .select("*")
            .neq("outcome_label", "UNRESOLVED")
            .is_("realized_return_net_of_costs", "null")
            .limit(limit)
            .execute()
        )
        return [DecisionOutcome.model_validate(row) for row in response.data]

    def update_net_of_costs(
        self, decision_id: str, realized_return_net_of_costs: float, assumed_fill_method: str
    ) -> None:
        self._client.table("decision_outcomes").update(
            {
                "realized_return_net_of_costs": realized_return_net_of_costs,
                "assumed_fill_method": assumed_fill_method,
            }
        ).eq("decision_id", decision_id).execute()

    def get_resolved_without_benchmark_alpha(self, limit: int = 500) -> list[DecisionOutcome]:
        """Phase 5b addendum: resolved rows still missing a real effective
        alpha -- lets `scripts/apply_benchmark_alpha.py` be re-run safely
        without recomputing already-processed rows, same convention as
        `get_resolved_without_net_of_costs` above."""
        response = (
            self._client.table("decision_outcomes")
            .select("*")
            .neq("outcome_label", "UNRESOLVED")
            .is_("effective_alpha", "null")
            .limit(limit)
            .execute()
        )
        return [DecisionOutcome.model_validate(row) for row in response.data]

    def update_benchmark_alpha(self, decision_id: str, benchmark_return: float, effective_alpha: float) -> None:
        self._client.table("decision_outcomes").update(
            {
                "benchmark_return": benchmark_return,
                "effective_alpha": effective_alpha,
            }
        ).eq("decision_id", decision_id).execute()

    def get_recent(self, limit: int = 200, is_backfilled: bool | None = None) -> list[DecisionOutcome]:
        """Phase 5: recent outcomes newest-first, for the calibration/ledger
        views — never mixes backfilled/live silently (see 3e.1's own
        non-negotiable)."""
        query = self._client.table("decision_outcomes").select("*")
        if is_backfilled is not None:
            query = query.eq("is_backfilled", is_backfilled)
        response = query.order("decision_timestamp", desc=True).limit(limit).execute()
        return [DecisionOutcome.model_validate(row) for row in response.data]

    def get_by_decision_id(self, decision_id: str) -> DecisionOutcome | None:
        response = self._client.table("decision_outcomes").select("*").eq("decision_id", decision_id).limit(1).execute()
        if not response.data:
            return None
        return DecisionOutcome.model_validate(response.data[0])


class CalibrationRunRepository:
    """Persists `calibration_runs` — every calibration/backtest attempt as a
    first-class, countable event (3e's baseline script, extended by 3g)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, record: CalibrationRunRecord) -> None:
        self._client.table("calibration_runs").insert(record.to_row()).execute()

    def get_recent(self, limit: int = 50) -> list[CalibrationRunRecord]:
        """Phase 5: every calibration attempt newest-first — the dashboard
        must show these as the distinct, method-tagged trials they are
        (never merged into one figure), same as 3g's own trial-count
        discipline."""
        response = (
            self._client.table("calibration_runs")
            .select("*")
            .order("run_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [CalibrationRunRecord.model_validate(row) for row in response.data]


class PortfolioPositionRepository:
    """Reads/writes `portfolio_positions` (migration 0007) — current state
    of the paper book, one row per asset with a nonzero-ever allocation."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_all(self) -> dict[str, PortfolioPosition]:
        response = self._client.table("portfolio_positions").select("*").execute()
        return {row["asset_id"]: PortfolioPosition.model_validate(row) for row in response.data}

    def upsert(self, position: PortfolioPosition) -> None:
        self._client.table("portfolio_positions").upsert(
            {
                "asset_id": position.asset_id,
                "current_allocation": position.current_allocation,
                "last_decision_id": position.last_decision_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ).execute()


class PortfolioAllocationChangeRepository:
    """Persists `portfolio_allocation_changes` — the append-only log
    MAX_WEEKLY_TURNOVER sums over a trailing window."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, change: PortfolioAllocationChange) -> None:
        self._client.table("portfolio_allocation_changes").insert(change.to_row()).execute()

    def get_turnover_since(self, since: datetime) -> float:
        response = (
            self._client.table("portfolio_allocation_changes")
            .select("previous_allocation, new_allocation")
            .gte("changed_at", since.isoformat())
            .execute()
        )
        return sum(
            abs(float(row["new_allocation"]) - float(row["previous_allocation"]))
            for row in response.data
        )


class HoldingsLedgerRepository:
    """Persists/reads `holdings_ledger` (Phase 5a) — the ground-truth
    "what do I actually own" input, append-only. The SOLE input to
    `current_allocation` going forward; `portfolio_positions` is retired
    as an input (see README's Phase 5a section)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, entry: HoldingsLedgerEntry) -> None:
        self._client.table("holdings_ledger").insert(entry.to_row()).execute()

    def get_latest_holdings(self) -> list[HoldingsLedgerEntry]:
        """The latest row per `asset_id` (including at most one cash row,
        `asset_id=None`) by `recorded_at` — never the full append-only
        history. Client-side dedup-by-first-seen-in-desc-order, same
        pattern already used for 3f's multi-entry macro evidence."""
        response = (
            self._client.table("holdings_ledger")
            .select("*")
            .order("recorded_at", desc=True)
            .execute()
        )
        seen: set[str | None] = set()
        latest: list[HoldingsLedgerEntry] = []
        for row in response.data:
            key = row["asset_id"]
            if key in seen:
                continue
            seen.add(key)
            latest.append(HoldingsLedgerEntry.model_validate(row))
        return latest

    def get_history(self, asset_id: str | None) -> list[HoldingsLedgerEntry]:
        """Every entry ever recorded for one asset (or the cash line, if
        `asset_id=None`), newest first — "what did I hold as of date T"
        stays answerable from this."""
        query = self._client.table("holdings_ledger").select("*")
        query = query.is_("asset_id", "null") if asset_id is None else query.eq("asset_id", asset_id)
        response = query.order("recorded_at", desc=True).execute()
        return [HoldingsLedgerEntry.model_validate(row) for row in response.data]

    def get_all_history(self) -> list[HoldingsLedgerEntry]:
        """Every entry ever recorded, across every asset and the cash
        line, newest first."""
        response = (
            self._client.table("holdings_ledger")
            .select("*")
            .order("recorded_at", desc=True)
            .execute()
        )
        return [HoldingsLedgerEntry.model_validate(row) for row in response.data]


class AdversarialResearchRepository:
    """Persists `adversarial_research` (3f) — one row per candidate per run,
    bull + bear + scenarios from one shared research cycle."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, record: AdversarialResearchRecord) -> None:
        self._client.table("adversarial_research").insert(record.to_row()).execute()

    def get_latest_by_asset(self, asset_id: str) -> AdversarialResearchRecord | None:
        response = (
            self._client.table("adversarial_research")
            .select("*")
            .eq("asset_id", asset_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return AdversarialResearchRecord.model_validate(response.data[0])

    def get_recent(self, limit: int = 50) -> list[AdversarialResearchRecord]:
        """Phase 5: recent bull/bear/scenario research across every asset,
        newest first."""
        response = (
            self._client.table("adversarial_research")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [AdversarialResearchRecord.model_validate(row) for row in response.data]


class JudgeReasoningAuditRepository:
    """Persists `judge_reasoning_audits` (3g task 5)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, record: JudgeReasoningAuditRecord) -> None:
        self._client.table("judge_reasoning_audits").insert(record.to_row()).execute()

    def get_recent(self, limit: int = 50) -> list[JudgeReasoningAuditRecord]:
        response = (
            self._client.table("judge_reasoning_audits")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [JudgeReasoningAuditRecord.model_validate(row) for row in response.data]

    def get_by_decision_id(self, decision_id: str) -> list[JudgeReasoningAuditRecord]:
        response = (
            self._client.table("judge_reasoning_audits")
            .select("*")
            .eq("decision_id", decision_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [JudgeReasoningAuditRecord.model_validate(row) for row in response.data]


class EvidenceValueReportRepository:
    """Persists `evidence_value_reports` (3h tasks 1/1a)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def insert(self, record: EvidenceValueReportRecord) -> None:
        self._client.table("evidence_value_reports").insert(record.to_row()).execute()

    def get_recent(self, limit: int = 50) -> list[EvidenceValueReportRecord]:
        response = (
            self._client.table("evidence_value_reports")
            .select("*")
            .order("run_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [EvidenceValueReportRecord.model_validate(row) for row in response.data]
