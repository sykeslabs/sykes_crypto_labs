from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.auth import verify_api_key
from app.api.dependencies import (
    get_asset_repo,
    get_asset_status_repo,
    get_binance_client,
    get_coinbase_client,
    get_coingecko_client,
    get_holdings_ledger_repo,
    get_market_snapshot_repo,
)
from app.api.main import app
from app.database.models import Asset
from app.portfolio.schemas import HoldingsLedgerEntry


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[verify_api_key] = lambda: None
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _default_live_price_clients():
    # Default: neither venue lists anything -- live_price_usd stays None.
    # Individual tests override these again if they want to exercise the
    # live-price-found path.
    app.dependency_overrides[get_binance_client] = lambda: FakeBinanceClient()
    app.dependency_overrides[get_coinbase_client] = lambda: FakeCoinbaseClient()
    yield


@pytest.fixture(autouse=True)
def _default_new_asset_dependencies():
    # Default: CoinGecko finds no real coin for whatever symbol was typed
    # (existing untracked-symbol tests exercise the real rejection path),
    # and asset-status writes go to a fake, never the real DB. Individual
    # tests override `get_coingecko_client` again to exercise the real
    # new-asset-creation path.
    app.dependency_overrides[get_coingecko_client] = lambda: FakeCoinGeckoClient()
    app.dependency_overrides[get_asset_status_repo] = lambda: FakeAssetStatusRepo()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _asset(asset_id="a1", symbol="BTC"):
    return Asset(id=asset_id, symbol=symbol, name=symbol, coingecko_id=symbol.lower(), active=True, in_asset=True, created_at=datetime.now(UTC))


def _tx(asset_id, quantity, cost_basis=None, transaction_type="BUY", minutes_ago=0, platform="coinbase"):
    return HoldingsLedgerEntry(
        asset_id=asset_id, quantity=quantity, cost_basis_usd=cost_basis,
        recorded_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        transaction_type=transaction_type, platform=platform,
    )


class FakeAssetRepo:
    def __init__(self, assets=None):
        self._assets = {a.id: a for a in (assets or [])}
        self.created = []
        self.update_in_asset_calls: list[tuple[str, bool]] = []

    def get_by_id(self, asset_id):
        return self._assets.get(asset_id)

    def get_by_symbol(self, symbol):
        for asset in self._assets.values():
            if asset.symbol.upper() == symbol.upper():
                return asset
        return None

    def get_by_coingecko_id(self, coingecko_id):
        for asset in self._assets.values():
            if asset.coingecko_id == coingecko_id:
                return asset
        return None

    def create_asset(self, symbol, name, coingecko_id, coinmarketcap_id=None, active=True, in_asset=False):
        new_id = f"new-{len(self._assets) + len(self.created) + 1}"
        asset = Asset(id=new_id, symbol=symbol, name=name, coingecko_id=coingecko_id, active=active, in_asset=in_asset, created_at=datetime.now(UTC))
        self._assets[new_id] = asset
        self.created.append(asset)
        return asset

    def get_active_assets(self):
        return list(self._assets.values())

    def update_in_asset(self, asset_id, in_asset):
        self.update_in_asset_calls.append((asset_id, in_asset))
        self._assets[asset_id].in_asset = in_asset


class FakeAssetStatusRepo:
    def __init__(self):
        self.changes = []

    def record_status_change(self, asset_id, status, reason=None):
        self.changes.append((asset_id, status, reason))


class FakeCoinGeckoClient:
    """Default: no real coin found for any symbol -- individual tests
    override `app.dependency_overrides[get_coingecko_client]` again with a
    real-match variant to exercise the new-asset-creation path."""

    def search_coin_by_symbol(self, symbol):
        return None


class FakeHoldingsLedgerRepo:
    def __init__(self, seed=None):
        self.inserted = list(seed or [])

    def insert(self, entry):
        self.inserted.append(entry)

    def get_history(self, asset_id):
        return sorted([e for e in self.inserted if e.asset_id == asset_id], key=lambda e: e.recorded_at, reverse=True)

    def get_all_history(self):
        return sorted(self.inserted, key=lambda e: e.recorded_at, reverse=True)


class FakeMarketSnapshotRepo:
    def __init__(self, price_by_asset_id=None):
        self._prices = price_by_asset_id or {}

    def get_latest_snapshot(self, asset_id):
        price = self._prices.get(asset_id)
        if price is None:
            return None
        return type("Snapshot", (), {"price": price, "timestamp": datetime.now(UTC)})()


class FakeBinanceClient:
    def fetch_ticker_24hr(self, symbol):
        return None  # not listed -- exercises the Coinbase fallback by default


class FakeCoinbaseClient:
    def fetch_ticker(self, symbol):
        return None  # neither venue lists it in these tests -- live_price_usd stays None


# --- Phase 5b: symbol lookup for the entry form --------------------------------

def test_get_valid_symbols_returns_sorted_active_symbols(client):
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="SOL"), _asset(asset_id="a2", symbol="BTC")])
    response = client.get("/holdings/valid-symbols")
    assert response.status_code == 200
    assert response.json() == ["BTC", "SOL"]


# --- validation rejection -----------------------------------------------------

def test_rejects_untracked_symbol_when_coingecko_also_has_no_real_match(client):
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo()  # no assets known
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo()
    # Default autouse FakeCoinGeckoClient also finds nothing real.
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "NOTREAL", "quantity": 1.0})
    assert response.status_code == 422
    assert "not a tracked asset symbol" in response.json()["detail"]
    assert "no real CoinGecko-listed token" in response.json()["detail"]


# --- Phase 5b (addendum): auto-creating a real, not-yet-tracked asset ----------

def test_creates_a_new_asset_when_coingecko_confirms_a_real_match(client):
    class FakeCoinGeckoWithMatch:
        def search_coin_by_symbol(self, symbol):
            assert symbol == "ADA"
            return {"id": "cardano", "symbol": "ada", "name": "Cardano", "market_cap_rank": 9}

    fake_asset_repo = FakeAssetRepo()
    fake_status_repo = FakeAssetStatusRepo()
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: fake_asset_repo
    app.dependency_overrides[get_asset_status_repo] = lambda: fake_status_repo
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    app.dependency_overrides[get_coingecko_client] = lambda: FakeCoinGeckoWithMatch()

    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "ADA", "quantity": 100.0})
    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "ADA"

    # A real new tracked asset was created -- active and in_asset (this
    # call is recording a real position in it right now), plus a real
    # asset_status_history entry, same audit trail 3b's screening
    # promotions get.
    assert len(fake_asset_repo.created) == 1
    created = fake_asset_repo.created[0]
    assert created.coingecko_id == "cardano"
    assert created.active is True
    assert created.in_asset is True
    assert len(fake_status_repo.changes) == 1
    assert fake_status_repo.changes[0][1] == "HELD"


def test_rejects_a_symbol_with_no_real_coingecko_coin_and_creates_nothing(client):
    fake_asset_repo = FakeAssetRepo()
    app.dependency_overrides[get_asset_repo] = lambda: fake_asset_repo
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo()
    # Default autouse FakeCoinGeckoClient finds nothing real for "FAKECOIN".
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "FAKECOIN", "quantity": 1.0})
    assert response.status_code == 422
    assert fake_asset_repo.created == []


def test_reuses_an_existing_asset_already_tracked_under_the_same_coingecko_id(client):
    # Guards against a duplicate row for the same real coin: the user
    # types a symbol not literally in our assets table (get_by_symbol
    # finds nothing), but CoinGecko's search resolves it to a coin whose
    # id IS already tracked here (e.g. under a different symbol/casing
    # history) -- mirrors 3b's screening promotion's own duplicate guard
    # (`_promote_new_candidates`'s `get_by_coingecko_id` check).
    existing = _asset(asset_id="a1", symbol="AVAX")  # coingecko_id="avax" per _asset()
    fake_asset_repo = FakeAssetRepo([existing])
    fake_status_repo = FakeAssetStatusRepo()
    app.dependency_overrides[get_asset_repo] = lambda: fake_asset_repo
    app.dependency_overrides[get_asset_status_repo] = lambda: fake_status_repo
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo()

    class FakeCoinGeckoResolvesToTrackedId:
        def search_coin_by_symbol(self, symbol):
            assert symbol == "AVALANCHE"
            return {"id": "avax", "symbol": "avax", "name": "Avalanche", "market_cap_rank": 20}

    app.dependency_overrides[get_coingecko_client] = lambda: FakeCoinGeckoResolvesToTrackedId()
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "AVALANCHE", "quantity": 1.0})
    assert response.status_code == 201
    assert response.json()["symbol"] == "AVAX"  # reused the existing tracked asset's real symbol
    assert fake_asset_repo.created == []  # no duplicate row created
    assert fake_status_repo.changes == []  # no new status entry -- nothing new was tracked


def test_symbol_lookup_is_case_insensitive(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="SOL")])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "sol", "quantity": 5.0})
    assert response.status_code == 201
    assert response.json()["symbol"] == "SOL"


def test_rejects_negative_quantity(client):
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo()
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": -1.0})
    assert response.status_code == 422


def test_rejects_negative_cost_basis(client):
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo()
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 1.0, "cost_basis_usd": -100.0})
    assert response.status_code == 422


def test_accepts_valid_asset_holding(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 2.5, "cost_basis_usd": 100.0})
    assert response.status_code == 201
    assert response.json()["quantity"] == 2.5
    assert len(fake_ledger.inserted) == 1


def test_accepts_cash_line(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo()
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "CASH", "quantity": 5000.0})
    assert response.status_code == 201
    assert response.json()["asset_id"] is None
    assert response.json()["symbol"] == "CASH"


def test_response_never_contains_a_decision_or_target_allocation_field(client):
    # Structural check on the non-negotiable: the response body must never
    # be able to carry a decision-relevant field, by construction.
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 1.0})
    body = response.json()
    assert "decision" not in body
    assert "target_allocation" not in body


# --- Phase 5b: SELL validation -------------------------------------------------

def test_sell_exceeding_current_holding_is_rejected(client):
    seed = [_tx("a1", 5.0, cost_basis=500.0, minutes_ago=60)]
    fake_ledger = FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="BTC")])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 9.0, "transaction_type": "SELL"})
    assert response.status_code == 422
    assert "Cannot sell" in response.json()["detail"]
    assert len(fake_ledger.inserted) == 1  # rejected -- never inserted


def test_sell_within_current_holding_is_accepted(client):
    seed = [_tx("a1", 5.0, cost_basis=500.0, minutes_ago=60)]
    fake_ledger = FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="BTC")])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 2.0, "transaction_type": "SELL"})
    assert response.status_code == 201
    assert len(fake_ledger.inserted) == 2


def test_sell_is_validated_against_the_specific_platform_not_the_cross_platform_total(client):
    # Real Phase 5o correctness fix: 5 BTC on Coinbase + 5 BTC on the
    # Ledger wallet is 10 BTC in aggregate, but you can't sell 9 "from
    # Coinbase" when only 5 actually sit there.
    seed = [
        _tx("a1", 5.0, cost_basis=500.0, minutes_ago=60, platform="coinbase"),
        _tx("a1", 5.0, cost_basis=500.0, minutes_ago=60, platform="ledger_wallet"),
    ]
    fake_ledger = FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="BTC")])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 9.0, "transaction_type": "SELL"})
    assert response.status_code == 422
    assert "Cannot sell" in response.json()["detail"]
    assert len(fake_ledger.inserted) == 2  # rejected -- never inserted

    # But selling within what THAT platform actually holds is fine.
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 4.0, "transaction_type": "SELL"})
    assert response.status_code == 201
    assert len(fake_ledger.inserted) == 3


def test_sell_of_cash_line_is_never_validated_against_a_position(client):
    # Cash isn't a summed position -- selling/reducing cash is just a new
    # absolute stated amount, no over-sell check applies to it.
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo()
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "CASH", "quantity": 100.0, "transaction_type": "SELL"})
    assert response.status_code == 201


# --- assets.in_asset sync (real reconciliation fix, 2026-09-13) ----------------
# assets.in_asset was previously only ever set once, at asset-creation time,
# and never updated again as real holdings changed (confirmed live via
# "S"/Sonic: in_asset=true with zero real transactions ever recorded).
# POST /holdings now recomputes the real aggregated position after every
# transaction and keeps in_asset genuinely in sync.

def test_buy_on_previously_zero_position_asset_sets_in_asset_true(client):
    fake_asset_repo = FakeAssetRepo([Asset(
        id="a1", symbol="LINK", name="LINK", coingecko_id="link",
        active=True, in_asset=False, created_at=datetime.now(UTC),
    )])
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: fake_asset_repo
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger

    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "LINK", "quantity": 10.0, "transaction_type": "BUY"})
    assert response.status_code == 201
    assert fake_asset_repo.update_in_asset_calls == [("a1", True)]
    assert fake_asset_repo._assets["a1"].in_asset is True


def test_sell_that_fully_closes_position_sets_in_asset_false(client):
    seed = [_tx("a1", 5.0, cost_basis=50.0, minutes_ago=60)]
    fake_asset_repo = FakeAssetRepo([Asset(
        id="a1", symbol="SONIC", name="Sonic", coingecko_id="sonic",
        active=True, in_asset=True, created_at=datetime.now(UTC),
    )])
    fake_ledger = FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: fake_asset_repo
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger

    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "SONIC", "quantity": 5.0, "transaction_type": "SELL"})
    assert response.status_code == 201
    assert fake_asset_repo.update_in_asset_calls == [("a1", False)]
    assert fake_asset_repo._assets["a1"].in_asset is False


def test_partial_sell_leaving_a_real_position_open_keeps_in_asset_true(client):
    # A SELL alone must never be assumed to fully close a position --
    # keyed off the real aggregated quantity after the transaction, not
    # transaction_type alone.
    seed = [_tx("a1", 10.0, cost_basis=100.0, minutes_ago=60)]
    fake_asset_repo = FakeAssetRepo([_asset(asset_id="a1", symbol="BTC")])  # in_asset=True already
    fake_ledger = FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: fake_asset_repo
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger

    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 4.0, "transaction_type": "SELL"})
    assert response.status_code == 201
    assert fake_asset_repo.update_in_asset_calls == [("a1", True)]


def test_cash_entries_never_touch_in_asset(client):
    fake_asset_repo = FakeAssetRepo()
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: fake_asset_repo
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger

    response = client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "CASH", "quantity": 1000.0})
    assert response.status_code == 201
    assert fake_asset_repo.update_in_asset_calls == []


# --- append-only, transactional (Phase 5b) -------------------------------------

def test_editing_a_holding_appends_a_new_row_never_overwrites(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger

    client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 1.0})
    client.post("/holdings", json={"platform": "coinbase", "asset_symbol": "BTC", "quantity": 2.0})  # a second, separate BUY transaction

    history_response = client.get("/holdings/history", params={"asset_id": "a1"})
    assert history_response.status_code == 200
    assert len(history_response.json()) == 2  # both entries preserved, not overwritten
    quantities = sorted(e["quantity"] for e in history_response.json())
    assert quantities == [1.0, 2.0]


def test_get_current_holdings_sums_multiple_buy_transactions(client):
    # Phase 5b: this is the whole point of the transactional model -- two
    # separate BUYs for the same asset must sum, not the second replacing
    # the first.
    seed = [
        _tx("a1", 5.0, cost_basis=500.0, minutes_ago=60),
        _tx("a1", 3.0, cost_basis=360.0, minutes_ago=10),
    ]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="SOL")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo({"a1": 100.0})
    response = TestClient(app).get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["quantity"] == pytest.approx(8.0)
    assert body[0]["cost_basis_usd"] == pytest.approx(860.0)


def test_get_current_holdings_returns_one_row_per_platform_for_the_same_asset(client):
    # Real Phase 5o behavior: the same asset held on two platforms shows
    # as two separate rows, each with its own cost basis/value/allocation
    # -- never merged into one, and never one platform's value silently
    # overwriting the other's (the real bug this endpoint's rewrite fixes).
    seed = [
        _tx("a1", 1.0, cost_basis=1000.0, platform="coinbase"),
        _tx("a1", 3.0, cost_basis=3000.0, platform="ledger_wallet"),
    ]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="BTC")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo({"a1": 100.0})
    response = TestClient(app).get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    by_platform = {r["platform"]: r for r in body}
    assert by_platform["coinbase"]["quantity"] == pytest.approx(1.0)
    assert by_platform["coinbase"]["value_usd"] == pytest.approx(100.0)
    assert by_platform["ledger_wallet"]["quantity"] == pytest.approx(3.0)
    assert by_platform["ledger_wallet"]["value_usd"] == pytest.approx(300.0)
    # Allocation is each row's own share of the TOTAL (400) -- not
    # recomputed independently per platform.
    assert by_platform["coinbase"]["allocation"] == pytest.approx(100.0 / 400.0)
    assert by_platform["ledger_wallet"]["allocation"] == pytest.approx(300.0 / 400.0)


def test_get_current_holdings_reflects_a_sell(client):
    seed = [
        _tx("a1", 10.0, cost_basis=1000.0, minutes_ago=60),
        _tx("a1", 4.0, transaction_type="SELL", minutes_ago=10),
    ]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="SOL")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo({"a1": 100.0})
    response = TestClient(app).get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["quantity"] == pytest.approx(6.0)
    assert body[0]["cost_basis_usd"] == pytest.approx(600.0)  # weighted-average-cost, 40% sold


def test_get_current_holdings_fully_sold_asset_does_not_appear(client):
    seed = [
        _tx("a1", 5.0, cost_basis=500.0, minutes_ago=60),
        _tx("a1", 5.0, transaction_type="SELL", minutes_ago=10),
    ]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="SOL")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo({"a1": 100.0})
    response = TestClient(app).get("/holdings")
    assert response.status_code == 200
    assert response.json() == []


# --- current-state derived fields ----------------------------------------------

def test_get_current_holdings_returns_latest_state(client):
    seed = [
        _tx("a1", 1.0, minutes_ago=10),
        _tx(None, 500.0, minutes_ago=10),
    ]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo()
    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2


def test_get_current_holdings_resolves_asset_id_to_a_real_symbol_not_a_raw_uuid(client):
    seed = [_tx("a1", 1.0, minutes_ago=10)]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="BTC")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo()
    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["asset_id"] == "a1"
    assert body[0]["symbol"] == "BTC"


def test_get_current_holdings_computes_real_allocation_comparable_to_portfolio_state(client):
    seed = [
        _tx("a1", 2.0, minutes_ago=10),  # 2 BTC @ 100 = 200
        _tx(None, 800.0, minutes_ago=10),  # $800 cash
    ]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="BTC")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo({"a1": 100.0})
    response = client.get("/holdings")
    assert response.status_code == 200
    body = {row["symbol"]: row for row in response.json()}
    # total value = 200 (BTC) + 800 (cash) = 1000 -> BTC 20%, CASH 80%
    assert body["BTC"]["allocation"] == pytest.approx(0.2)
    assert body["CASH"]["allocation"] == pytest.approx(0.8)


def test_get_current_holdings_computes_real_value_usd_for_asset_and_cash_rows(client):
    seed = [
        _tx("a1", 2.0, minutes_ago=10),  # 2 BTC @ 100 = $200
        _tx(None, 800.0, minutes_ago=10),  # $800 cash
    ]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="BTC")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo({"a1": 100.0})
    response = client.get("/holdings")
    assert response.status_code == 200
    body = {row["symbol"]: row for row in response.json()}
    assert body["BTC"]["value_usd"] == pytest.approx(200.0)  # quantity * price, never a fabricated 0
    assert body["CASH"]["value_usd"] == pytest.approx(800.0)  # quantity directly, no price lookup
    total_value_usd = sum(row["value_usd"] for row in body.values())
    assert total_value_usd == pytest.approx(1000.0)  # real total, summable client-side


def test_get_current_holdings_leaves_value_usd_none_when_no_price_available(client):
    seed = [_tx("a1", 2.0, minutes_ago=10)]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="BTC")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo()  # no price for a1
    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["value_usd"] is None  # never a fabricated 0 when the real price is unknown


def test_get_current_holdings_computes_cost_per_unit_and_unrealized_pnl(client):
    # Bought 5 @ total $500 ($100/unit). Current price $130 -> value $650,
    # P&L = +$150 = +30%.
    seed = [_tx("a1", 5.0, cost_basis=500.0, minutes_ago=10)]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="SOL")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo({"a1": 130.0})
    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()[0]
    assert body["cost_per_unit"] == pytest.approx(100.0)
    assert body["unrealized_pnl_usd"] == pytest.approx(150.0)
    assert body["unrealized_pnl_pct"] == pytest.approx(30.0)


def test_get_current_holdings_leaves_pnl_none_when_no_cost_basis_entered(client):
    seed = [_tx("a1", 5.0, cost_basis=None, minutes_ago=10)]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="SOL")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo({"a1": 130.0})
    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()[0]
    assert body["cost_per_unit"] is None
    assert body["unrealized_pnl_usd"] is None


def test_get_current_holdings_live_price_from_binance(client):
    seed = [_tx("a1", 2.0, minutes_ago=10)]

    class FakeBinanceWithTicker:
        def fetch_ticker_24hr(self, symbol):
            assert symbol == "BTC"
            return {"lastPrice": "123.45", "closeTime": 1700000000000}

    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="BTC")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo()
    app.dependency_overrides[get_binance_client] = lambda: FakeBinanceWithTicker()
    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["live_price_usd"] == pytest.approx(123.45)
    assert body[0]["live_price_source"] == "binance"
    assert body[0]["live_price_as_of"] is not None


def test_get_current_holdings_live_price_falls_back_to_coinbase(client):
    seed = [_tx("a1", 2.0, minutes_ago=10)]

    class FakeCoinbaseWithTicker:
        def fetch_ticker(self, symbol):
            assert symbol == "BTC"
            return {"price": "678.90", "time": "2026-09-06T12:00:00Z"}

    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(asset_id="a1", symbol="BTC")])
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo()
    # get_binance_client stays the default "not listed" fake -- Coinbase fallback exercised
    app.dependency_overrides[get_coinbase_client] = lambda: FakeCoinbaseWithTicker()
    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["live_price_usd"] == pytest.approx(678.90)
    assert body[0]["live_price_source"] == "coinbase"


def test_get_current_holdings_shows_cash_symbol_for_the_null_asset_id_line(client):
    seed = [_tx(None, 500.0, minutes_ago=10)]
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo(seed)
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo()
    app.dependency_overrides[get_market_snapshot_repo] = lambda: FakeMarketSnapshotRepo()
    response = client.get("/holdings")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["asset_id"] is None
    assert body[0]["symbol"] == "CASH"


# --- purchased_at / transaction_type pass-through -------------------------------

def test_purchased_at_and_transaction_type_round_trip(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset(symbol="SOL")])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"platform": "coinbase", 
        "asset_symbol": "SOL", "quantity": 5.0, "cost_basis_usd": 500.0,
        "purchased_at": "2026-08-15T00:00:00Z", "transaction_type": "BUY",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["purchased_at"].startswith("2026-08-15")
    assert body["transaction_type"] == "BUY"

    history_response = client.get("/holdings/history", params={"asset_id": "a1"})
    assert history_response.json()[0]["purchased_at"].startswith("2026-08-15")
