from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.auth import verify_api_key
from app.api.dependencies import get_asset_repo, get_holdings_ledger_repo
from app.api.main import app
from app.database.models import Asset
from app.portfolio.schemas import HoldingsLedgerEntry


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[verify_api_key] = lambda: None
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _asset(asset_id="a1", symbol="BTC"):
    return Asset(id=asset_id, symbol=symbol, name=symbol, coingecko_id=symbol.lower(), active=True, in_asset=True, created_at=datetime.now(UTC))


class FakeAssetRepo:
    def __init__(self, assets=None):
        self._assets = {a.id: a for a in (assets or [])}

    def get_by_id(self, asset_id):
        return self._assets.get(asset_id)


class FakeHoldingsLedgerRepo:
    def __init__(self):
        self.inserted = []

    def insert(self, entry):
        self.inserted.append(entry)

    def get_latest_holdings(self):
        return self.inserted

    def get_history(self, asset_id):
        return [e for e in self.inserted if e.asset_id == asset_id]

    def get_all_history(self):
        return self.inserted


# --- validation rejection -----------------------------------------------------

def test_rejects_untracked_asset(client):
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo()  # no assets known
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo()
    response = client.post("/holdings", json={"asset_id": "nonexistent", "quantity": 1.0})
    assert response.status_code == 422
    assert "not a tracked asset" in response.json()["detail"]


def test_rejects_negative_quantity(client):
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo()
    response = client.post("/holdings", json={"asset_id": "a1", "quantity": -1.0})
    assert response.status_code == 422


def test_rejects_negative_cost_basis(client):
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeHoldingsLedgerRepo()
    response = client.post("/holdings", json={"asset_id": "a1", "quantity": 1.0, "cost_basis_usd": -100.0})
    assert response.status_code == 422


def test_accepts_valid_asset_holding(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"asset_id": "a1", "quantity": 2.5, "cost_basis_usd": 100.0})
    assert response.status_code == 201
    assert response.json()["quantity"] == 2.5
    assert len(fake_ledger.inserted) == 1


def test_accepts_cash_line_with_null_asset_id(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo()
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"asset_id": None, "quantity": 5000.0})
    assert response.status_code == 201
    assert response.json()["asset_id"] is None


def test_response_never_contains_a_decision_or_target_allocation_field(client):
    # Structural check on the non-negotiable: the response body must never
    # be able to carry a decision-relevant field, by construction.
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger
    response = client.post("/holdings", json={"asset_id": "a1", "quantity": 1.0})
    body = response.json()
    assert "decision" not in body
    assert "target_allocation" not in body


# --- append-only history -------------------------------------------------------

def test_editing_a_holding_appends_a_new_row_never_overwrites(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger

    client.post("/holdings", json={"asset_id": "a1", "quantity": 1.0})
    client.post("/holdings", json={"asset_id": "a1", "quantity": 2.0})  # "edit" = a new entry

    history_response = client.get("/holdings/history", params={"asset_id": "a1"})
    assert history_response.status_code == 200
    assert len(history_response.json()) == 2  # both entries preserved, not overwritten
    quantities = [e["quantity"] for e in history_response.json()]
    assert quantities == [1.0, 2.0]


def test_removing_a_holding_is_a_new_zero_quantity_row_not_a_deletion(client):
    fake_ledger = FakeHoldingsLedgerRepo()
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo([_asset()])
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: fake_ledger

    client.post("/holdings", json={"asset_id": "a1", "quantity": 1.0})
    remove_response = client.post("/holdings", json={"asset_id": "a1", "quantity": 0.0})
    assert remove_response.status_code == 201

    history_response = client.get("/holdings/history", params={"asset_id": "a1"})
    assert len(history_response.json()) == 2  # the original row is still there


def test_get_current_holdings_returns_latest_state(client):
    entries = [
        HoldingsLedgerEntry(asset_id="a1", quantity=1.0, recorded_at=datetime.now(UTC)),
        HoldingsLedgerEntry(asset_id=None, quantity=500.0, recorded_at=datetime.now(UTC)),
    ]

    class FakeRepo:
        def get_latest_holdings(self):
            return entries

    app.dependency_overrides[get_holdings_ledger_repo] = lambda: FakeRepo()
    response = client.get("/holdings")
    assert response.status_code == 200
    assert len(response.json()) == 2
