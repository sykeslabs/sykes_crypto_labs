from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.config.settings import Settings
from app.database.models import Asset
from app.market_data.normalize import normalize_coingecko_entry
from app.market_data.service import MarketDataCollectionService

RAW_ENTRY = {
    "id": "bitcoin",
    "current_price": 65000.42,
    "market_cap": 1280000000000,
    "total_volume": 32000000000,
    "price_change_percentage_24h_in_currency": 1.23,
    "price_change_percentage_7d_in_currency": -3.4,
    "price_change_percentage_30d_in_currency": 10.5,
    "last_updated": "2026-09-03T12:00:00.000Z",
}


def test_normalize_produces_decimal_and_utc_timestamp():
    snapshot = normalize_coingecko_entry("asset-uuid", RAW_ENTRY)

    assert snapshot.asset_id == "asset-uuid"
    assert snapshot.price == Decimal("65000.42")
    assert snapshot.market_cap == Decimal("1280000000000")
    assert snapshot.price_change_7d == Decimal("-3.4")
    assert snapshot.timestamp == datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    assert snapshot.source == "coingecko"


def test_normalize_raises_without_price():
    entry = dict(RAW_ENTRY)
    del entry["current_price"]
    try:
        normalize_coingecko_entry("asset-uuid", entry)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_normalize_handles_missing_optional_fields():
    entry = {"id": "bitcoin", "current_price": 100, "last_updated": "2026-09-03T00:00:00.000Z"}
    snapshot = normalize_coingecko_entry("asset-uuid", entry)
    assert snapshot.market_cap is None
    assert snapshot.volume_24h is None
    assert snapshot.price_change_24h is None


def test_snapshot_to_row_is_json_safe():
    snapshot = normalize_coingecko_entry("asset-uuid", RAW_ENTRY)
    row = snapshot.to_row()
    assert row["price"] == "65000.42"
    assert isinstance(row["timestamp"], str)


class FakeAssetRepository:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeSnapshotRepository:
    def __init__(self, latest_timestamps=None):
        self._latest = latest_timestamps or {}
        self.inserted = []

    def get_latest_snapshot_timestamp(self, asset_id):
        return self._latest.get(asset_id)

    def insert_snapshot(self, snapshot):
        self.inserted.append(snapshot)


class FakeCoinGeckoClient:
    def __init__(self, markets):
        self._markets = markets

    def fetch_markets(self, coingecko_ids):
        return self._markets


def _make_asset(symbol="BTC", coingecko_id="bitcoin", asset_id="asset-1"):
    return Asset(
        id=asset_id,
        symbol=symbol,
        name=symbol,
        coingecko_id=coingecko_id,
        active=True,
        created_at=datetime.now(UTC),
    )


def test_service_inserts_new_snapshot():
    asset = _make_asset()
    settings = Settings(_env_file=None)
    snapshot_repo = FakeSnapshotRepository()
    service = MarketDataCollectionService(
        settings=settings,
        asset_repo=FakeAssetRepository([asset]),
        snapshot_repo=snapshot_repo,
        coingecko_client=FakeCoinGeckoClient({"bitcoin": RAW_ENTRY}),
    )

    result = service.run()

    assert result.inserted == ["BTC"]
    assert result.skipped_duplicate == []
    assert result.failed == []
    assert len(snapshot_repo.inserted) == 1


def test_service_skips_duplicate_within_interval():
    asset = _make_asset()
    settings = Settings(_env_file=None, min_snapshot_interval_minutes=5)
    recent_timestamp = datetime(2026, 9, 3, 11, 58, 0, tzinfo=UTC)  # 2 min before entry
    snapshot_repo = FakeSnapshotRepository(latest_timestamps={"asset-1": recent_timestamp})
    service = MarketDataCollectionService(
        settings=settings,
        asset_repo=FakeAssetRepository([asset]),
        snapshot_repo=snapshot_repo,
        coingecko_client=FakeCoinGeckoClient({"bitcoin": RAW_ENTRY}),
    )

    result = service.run()

    assert result.inserted == []
    assert result.skipped_duplicate == ["BTC"]
    assert snapshot_repo.inserted == []


def test_service_inserts_when_outside_interval():
    asset = _make_asset()
    settings = Settings(_env_file=None, min_snapshot_interval_minutes=5)
    old_timestamp = datetime(2026, 9, 3, 11, 0, 0, tzinfo=UTC)  # 1 hour before entry
    snapshot_repo = FakeSnapshotRepository(latest_timestamps={"asset-1": old_timestamp})
    service = MarketDataCollectionService(
        settings=settings,
        asset_repo=FakeAssetRepository([asset]),
        snapshot_repo=snapshot_repo,
        coingecko_client=FakeCoinGeckoClient({"bitcoin": RAW_ENTRY}),
    )

    result = service.run()

    assert result.inserted == ["BTC"]
    assert len(snapshot_repo.inserted) == 1


def test_service_handles_missing_market_data_without_crashing():
    asset = _make_asset(symbol="XRP", coingecko_id="ripple", asset_id="asset-2")
    settings = Settings(_env_file=None)
    snapshot_repo = FakeSnapshotRepository()
    service = MarketDataCollectionService(
        settings=settings,
        asset_repo=FakeAssetRepository([asset]),
        snapshot_repo=snapshot_repo,
        coingecko_client=FakeCoinGeckoClient({}),  # no data returned for XRP
    )

    result = service.run()

    assert result.inserted == []
    assert len(result.failed) == 1
    assert result.failed[0][0] == "XRP"


def test_service_handles_coingecko_failure_gracefully():
    class FailingCoinGeckoClient:
        def fetch_markets(self, coingecko_ids):
            raise RuntimeError("network down")

    asset = _make_asset()
    settings = Settings(_env_file=None)
    service = MarketDataCollectionService(
        settings=settings,
        asset_repo=FakeAssetRepository([asset]),
        snapshot_repo=FakeSnapshotRepository(),
        coingecko_client=FailingCoinGeckoClient(),
    )

    result = service.run()

    assert result.inserted == []
    assert len(result.failed) == 1
    assert "network down" in result.failed[0][1]


def test_service_no_active_assets_returns_empty_result():
    settings = Settings(_env_file=None)
    service = MarketDataCollectionService(
        settings=settings,
        asset_repo=FakeAssetRepository([]),
        snapshot_repo=FakeSnapshotRepository(),
        coingecko_client=FakeCoinGeckoClient({}),
    )

    result = service.run()

    assert result.inserted == []
    assert result.failed == []
