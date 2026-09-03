from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, loaded from environment / .env.

    Only Supabase credentials are required for Phase 1. Everything else has a
    safe default so the app can run with a minimal .env.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase (required)
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None

    # CoinGecko (optional — falls back to public unauthenticated endpoint)
    coingecko_api_key: SecretStr | None = None
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"

    # Only used by scripts/apply_migration.py, not by the core app.
    database_url: str | None = None

    # Market data behavior
    min_snapshot_interval_minutes: int = 5
    vs_currency: str = "usd"

    # Logging
    log_level: str = "INFO"

    def require_supabase(self) -> tuple[str, str]:
        """Return (url, service_role_key) or raise a clear error if missing."""
        if not self.supabase_url or not self.supabase_service_role_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in your .env file. "
                "Copy .env.example to .env and fill them in from your Supabase project settings."
            )
        return self.supabase_url, self.supabase_service_role_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
