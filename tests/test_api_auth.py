from fastapi.testclient import TestClient

from app.api.main import app
from app.config.settings import Settings


def _client_with_key(monkeypatch, configured_key="real-secret-key"):
    settings = Settings(_env_file=None, x_api_key=configured_key)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: settings)
    return TestClient(app)


def test_health_check_requires_no_api_key():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_endpoint_rejects_missing_api_key(monkeypatch):
    client = _client_with_key(monkeypatch)
    response = client.get("/signal-sources")
    assert response.status_code == 401


def test_endpoint_rejects_wrong_api_key(monkeypatch):
    client = _client_with_key(monkeypatch)
    response = client.get("/signal-sources", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401


def test_endpoint_accepts_correct_api_key(monkeypatch):
    from app.api.dependencies import get_signal_source_repo

    class FakeSignalSourceRepo:
        def get_all(self):
            return []

    app.dependency_overrides[get_signal_source_repo] = lambda: FakeSignalSourceRepo()
    try:
        client = _client_with_key(monkeypatch)
        response = client.get("/signal-sources", headers={"X-API-Key": "real-secret-key"})
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.clear()


def test_missing_configured_key_raises_runtime_error(monkeypatch):
    # require_x_api_key() must raise if X_API_KEY was never set --
    # never silently allow unauthenticated access as a fallback.
    settings = Settings(_env_file=None, x_api_key=None)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: settings)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/signal-sources", headers={"X-API-Key": "anything"})
    assert response.status_code == 500  # caught by the global handler, not leaked
    assert "X_API_KEY" not in response.text
