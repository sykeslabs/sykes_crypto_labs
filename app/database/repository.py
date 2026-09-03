from datetime import datetime

from supabase import Client

from app.database.models import Asset
from app.market_data.schemas import MarketSnapshot


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

    def insert_snapshot(self, snapshot: MarketSnapshot) -> None:
        self._client.table("market_snapshots").insert(snapshot.to_row()).execute()
