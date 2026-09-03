import pytest

from app.config.settings import Settings


def test_defaults_do_not_require_credentials():
    settings = Settings(_env_file=None)
    assert settings.min_snapshot_interval_minutes == 5
    assert settings.vs_currency == "usd"
    assert settings.coingecko_base_url == "https://api.coingecko.com/api/v3"
    assert settings.supabase_url is None
    assert settings.supabase_service_role_key is None


def test_require_supabase_raises_when_missing():
    settings = Settings(_env_file=None)
    with pytest.raises(RuntimeError):
        settings.require_supabase()


def test_require_supabase_returns_values_when_present():
    settings = Settings(
        _env_file=None,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="secret-key",
    )
    url, key = settings.require_supabase()
    assert url == "https://example.supabase.co"
    assert key == "secret-key"


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("MIN_SNAPSHOT_INTERVAL_MINUTES", "10")
    monkeypatch.setenv("VS_CURRENCY", "eur")
    settings = Settings(_env_file=None)
    assert settings.min_snapshot_interval_minutes == 10
    assert settings.vs_currency == "eur"
