from datetime import UTC, datetime

from supabase import Client

from app.database.models import Asset, AssetStatusHistory, AssetStatusValue, SignalSource
from app.llm.schemas import LLMAnalysisRecord
from app.market_data.schemas import MarketSnapshot
from app.news.schemas import NewsArticle


class AssetRepository:
    """Reads the configurable asset universe from the `assets` table."""

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
