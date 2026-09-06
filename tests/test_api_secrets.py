"""Phase 5 non-negotiable: no endpoint or error path may ever return a
configured secret, including in a stack trace on a 500. This deliberately
triggers an error path where the raised exception's own message contains a
realistic secret substring, and asserts it never reaches the response body.
"""

from fastapi.testclient import TestClient

from app.api.auth import verify_api_key
from app.api.dependencies import get_signal_source_repo
from app.api.main import app

FAKE_SUPABASE_KEY = "sb_secret_service_role_key_abc123xyz"
FAKE_OPENROUTER_KEY = "sk-or-v1-fake-secret-abc123"
FAKE_DATABASE_URL = "postgresql://postgres:supersecretpassword@db.example.com:5432/postgres"


def test_unhandled_exception_never_leaks_a_secret_embedded_in_its_own_message():
    class LeakySecretRepo:
        def get_all(self):
            # Simulates the worst case: a lower-level client's exception
            # message happens to embed a real configured secret (e.g. a
            # connection-string error) -- the global handler must still
            # never surface it.
            raise RuntimeError(
                f"Connection failed using key={FAKE_SUPABASE_KEY} "
                f"openrouter={FAKE_OPENROUTER_KEY} url={FAKE_DATABASE_URL}"
            )

    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[get_signal_source_repo] = lambda: LeakySecretRepo()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/signal-sources")
        assert response.status_code == 500
        body_text = response.text
        assert FAKE_SUPABASE_KEY not in body_text
        assert FAKE_OPENROUTER_KEY not in body_text
        assert FAKE_DATABASE_URL not in body_text
        assert response.json() == {"detail": "Internal server error"}
    finally:
        app.dependency_overrides.clear()


def test_holdings_unhandled_exception_never_leaks_a_secret_embedded_in_its_own_message():
    from app.api.dependencies import get_asset_repo, get_holdings_ledger_repo

    class LeakySecretAssetRepo:
        def get_by_id(self, asset_id):
            raise RuntimeError(
                f"Connection failed using key={FAKE_SUPABASE_KEY} "
                f"openrouter={FAKE_OPENROUTER_KEY} url={FAKE_DATABASE_URL}"
            )

    app.dependency_overrides[verify_api_key] = lambda: None
    app.dependency_overrides[get_asset_repo] = lambda: LeakySecretAssetRepo()
    app.dependency_overrides[get_holdings_ledger_repo] = lambda: type("R", (), {"insert": lambda self, e: None})()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/holdings", json={"asset_id": "a1", "quantity": 1.0})
        assert response.status_code == 500
        body_text = response.text
        assert FAKE_SUPABASE_KEY not in body_text
        assert FAKE_OPENROUTER_KEY not in body_text
        assert FAKE_DATABASE_URL not in body_text
        assert response.json() == {"detail": "Internal server error"}
    finally:
        app.dependency_overrides.clear()


def test_401_error_body_never_echoes_the_submitted_key():
    # A wrong API key submitted by a caller must never be reflected back
    # in the error body (defense against a caller accidentally pasting a
    # real key from another system into this one and having it echoed).
    from app.api.dependencies import get_settings_dependency  # noqa: F401
    from app.config.settings import Settings

    settings = Settings(_env_file=None, api_access_key="real-key")

    import app.api.auth as auth_module
    original = auth_module.get_settings
    auth_module.get_settings = lambda: settings
    try:
        client = TestClient(app)
        response = client.get("/signal-sources", headers={"X-API-Key": FAKE_OPENROUTER_KEY})
        assert response.status_code == 401
        assert FAKE_OPENROUTER_KEY not in response.text
    finally:
        auth_module.get_settings = original
