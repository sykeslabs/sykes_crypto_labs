from datetime import UTC, datetime

from supabase import Client

from app.database.models import Asset, AssetStatusHistory, AssetStatusValue, SignalSource
from app.llm.assessment_schemas import ModelMarketAssessmentRecord
from app.llm.schemas import LLMAnalysisRecord
from app.market_data.evidence_schemas import EvidenceObservation
from app.market_data.schemas import MarketSnapshot
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset
from app.news.schemas import NewsArticle


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

    def record_status_change(
        self, asset_id: str, status: AssetStatusValue, reason: str | None = None
    ) -> None:
        entry = AssetStatusHistory(
            asset_id=asset_id, status=status, reason=reason, changed_at=datetime.now(UTC)
        )
        self._client.table("asset_status_history").insert(entry.to_row()).execute()


class SignalSourceRepository:
    """Reads the `signal_sources` registry — which evidence sources exist,
    whether they're enabled, and their current status."""

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

    def get_latest_by_asset(self, asset_id: str, limit: int = 50) -> list[EvidenceObservation]:
        """Recent observations for one asset across every 3c/3f source —
        callers dedupe by `source` (first/latest occurrence wins) when
        building a per-asset context."""
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
