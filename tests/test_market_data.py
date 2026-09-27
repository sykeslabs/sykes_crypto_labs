from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.config.settings import Settings
from app.database.models import Asset
from app.market_data.normalize import normalize_coingecko_entry
from app.market_data.service import MarketDataCollectionService
from app.portfolio.schemas import HoldingsLedgerEntry

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
    def __init__(self, assets, inactive_assets=None):
        self._assets = assets
        self._all_assets = assets + (inactive_assets or [])

    def get_active_assets(self):
        return self._assets

    def get_by_id(self, asset_id):
        return next((a for a in self._all_assets if a.id == asset_id), None)


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


class FakeHoldingsLedgerRepo:
    """Empty by default for every existing test above -- the held-but-
    inactive merge below is what actually exercises real entries."""
    def __init__(self, entries=None):
        self._entries = entries or []

    def get_all_history(self):
        return self._entries


def _make_asset(symbol="BTC", coingecko_id="bitcoin", asset_id="asset-1", in_asset=True):
    return Asset(
        id=asset_id,
        symbol=symbol,
        name=symbol,
        coingecko_id=coingecko_id,
        active=True,
        in_asset=in_asset,
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
        holdings_ledger_repo=FakeHoldingsLedgerRepo(),
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
        holdings_ledger_repo=FakeHoldingsLedgerRepo(),
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
        holdings_ledger_repo=FakeHoldingsLedgerRepo(),
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
        holdings_ledger_repo=FakeHoldingsLedgerRepo(),
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
        holdings_ledger_repo=FakeHoldingsLedgerRepo(),
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
        holdings_ledger_repo=FakeHoldingsLedgerRepo(),
    )

    result = service.run()

    assert result.inserted == []
    assert result.failed == []


# --- Phase 5o (2026-09-27): held-but-inactive assets still get priced --------

def test_held_but_inactive_asset_is_included_in_collection():
    # Real gap found live: an 18.84 ETC position (active=False, kept that
    # way deliberately so it doesn't enter screening/Judge coverage) never
    # got a market_snapshots row, so GET /holdings could never compute its
    # Value/Allocation. A real nonzero holding must still get priced.
    active_asset = _make_asset(symbol="BTC", coingecko_id="bitcoin", asset_id="asset-1")
    held_inactive = Asset(
        id="asset-2", symbol="ETC", name="Ethereum Classic", coingecko_id="ethereum-classic",
        active=False, in_asset=True, created_at=datetime.now(UTC),
    )
    holdings_repo = FakeHoldingsLedgerRepo([
        HoldingsLedgerEntry(
            asset_id="asset-2", quantity=18.84, recorded_at=datetime.now(UTC), platform="ledger_wallet",
        ),
    ])
    snapshot_repo = FakeSnapshotRepository()
    service = MarketDataCollectionService(
        settings=Settings(_env_file=None),
        asset_repo=FakeAssetRepository([active_asset], inactive_assets=[held_inactive]),
        snapshot_repo=snapshot_repo,
        coingecko_client=FakeCoinGeckoClient({"bitcoin": RAW_ENTRY, "ethereum-classic": {**RAW_ENTRY, "id": "ethereum-classic"}}),
        holdings_ledger_repo=holdings_repo,
    )

    result = service.run()

    assert sorted(result.inserted) == ["BTC", "ETC"]


def test_inactive_asset_with_no_real_holding_is_not_included():
    active_asset = _make_asset(symbol="BTC", coingecko_id="bitcoin", asset_id="asset-1")
    untouched_inactive = Asset(
        id="asset-3", symbol="RANDOM", name="Random", coingecko_id="random-coin",
        active=False, in_asset=False, created_at=datetime.now(UTC),
    )
    service = MarketDataCollectionService(
        settings=Settings(_env_file=None),
        asset_repo=FakeAssetRepository([active_asset], inactive_assets=[untouched_inactive]),
        snapshot_repo=FakeSnapshotRepository(),
        coingecko_client=FakeCoinGeckoClient({"bitcoin": RAW_ENTRY}),
        holdings_ledger_repo=FakeHoldingsLedgerRepo([]),  # nothing ever held
    )

    result = service.run()

    assert result.inserted == ["BTC"]  # RANDOM never touched -- no real holding, no reason to price it


def test_zero_quantity_position_in_an_inactive_asset_is_not_included():
    # A fully-exited historical position (net quantity 0 after aggregation)
    # is not "held" -- must not force a price fetch either.
    active_asset = _make_asset(symbol="BTC", coingecko_id="bitcoin", asset_id="asset-1")
    fully_exited = Asset(
        id="asset-4", symbol="CGLD", name="Celo", coingecko_id="celo",
        active=False, in_asset=False, created_at=datetime.now(UTC),
    )
    holdings_repo = FakeHoldingsLedgerRepo([
        HoldingsLedgerEntry(asset_id="asset-4", quantity=10.0, recorded_at=datetime.now(UTC), platform="coinbase"),
        HoldingsLedgerEntry(
            asset_id="asset-4", quantity=10.0, recorded_at=datetime.now(UTC),
            transaction_type="SELL", platform="coinbase",
        ),
    ])
    service = MarketDataCollectionService(
        settings=Settings(_env_file=None),
        asset_repo=FakeAssetRepository([active_asset], inactive_assets=[fully_exited]),
        snapshot_repo=FakeSnapshotRepository(),
        coingecko_client=FakeCoinGeckoClient({"bitcoin": RAW_ENTRY}),
        holdings_ledger_repo=holdings_repo,
    )

    result = service.run()

    assert result.inserted == ["BTC"]
