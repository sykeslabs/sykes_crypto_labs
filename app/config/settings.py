from decimal import Decimal
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration, loaded from environment / .env.

    Only Supabase credentials are required for Phase 1. OpenRouter credentials
    are required only when running with --with-llm (Phase 2). Everything else
    has a safe default so the app can run with a minimal .env.
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

    # OpenRouter / LLM research (required only for --with-llm)
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    claude_model: str | None = None
    openai_model: str | None = None
    gemini_model: str | None = None
    llm_request_timeout_seconds: int = 60
    prompt_version: str = "v1"
    max_daily_llm_cost: Decimal = Decimal("5.00")
    max_monthly_llm_cost: Decimal = Decimal("50.00")

    # News collection (used only alongside --with-llm)
    news_lookback_hours: int = 24
    max_news_articles_per_asset: int = 5

    # Screening / regime classification (Phase 3b, used only with --with-screening)
    # CoinMarketCap: optional. Without a key, it's reported NOT_IMPLEMENTED in
    # signal_sources rather than approximated — never silently skipped without
    # a trace.
    coinmarketcap_api_key: SecretStr | None = None
    coinmarketcap_base_url: str = "https://pro-api.coinmarketcap.com"
    coinbase_base_url: str = "https://api.exchange.coinbase.com"
    binance_base_url: str = "https://api.binance.com"
    # 30, not the suggested range's upper end of 50 — CoinGecko's free-tier
    # per-asset historical endpoint rate-limits after ~5 rapid calls, and
    # every other per-asset call (Coinbase/Binance klines, CMC quotes) adds
    # runtime; keeping the universe modest keeps a screening run fast and
    # reliable rather than racing free-tier limits every run.
    screening_universe_size: int = 30
    top_candidates_size: int = 10

    # Derivatives / on-chain evidence (Phase 3c, used only with --with-derivatives)
    binance_futures_base_url: str = "https://fapi.binance.com"
    deribit_base_url: str = "https://www.deribit.com/api/v2"
    cftc_base_url: str = "https://publicreporting.cftc.gov"
    defillama_base_url: str = "https://api.llama.fi"
    defillama_stablecoins_base_url: str = "https://stablecoins.llama.fi"
    # Etherscan v2 API. Optional — free tier at etherscan.io/apis. Without a
    # key, reported NOT_IMPLEMENTED, never approximated.
    etherscan_api_key: SecretStr | None = None
    etherscan_base_url: str = "https://api.etherscan.io/v2/api"
    # Glassnode (on-chain valuation metrics: MVRV/SOPR/NUPL/cohorts, miner
    # metrics). Optional — very likely a paid tier for these specific
    # metrics; deliberately not subscribed to yet (see README). Client is
    # built and ready; reports NOT_IMPLEMENTED until a key is added.
    glassnode_api_key: SecretStr | None = None
    glassnode_base_url: str = "https://api.glassnode.com"

    # Multi-model current market assessment (Phase 3d, used only with
    # --with-assessment). Optional "name:slug,name:slug,..." override; if
    # unset, defaults to reusing Phase 2's CLAUDE_MODEL/OPENAI_MODEL/
    # GEMINI_MODEL (get_assessment_models() below) so this stage needs zero
    # new required config while staying independently overridable.
    openrouter_assessment_models: str | None = None
    assessment_prompt_version: str = "v1"

    # Logging
    log_level: str = "INFO"

    def get_assessment_models(self) -> dict[str, str]:
        """Returns {provider_name: model_slug} for 3d's assessment stage."""
        if self.openrouter_assessment_models:
            result = {}
            for pair in self.openrouter_assessment_models.split(","):
                name, _, slug = pair.partition(":")
                if name.strip() and slug.strip():
                    result[name.strip()] = slug.strip()
            return result
        return {
            name: slug
            for name, slug in (
                ("claude", self.claude_model),
                ("openai", self.openai_model),
                ("gemini", self.gemini_model),
            )
            if slug
        }

    def require_supabase(self) -> tuple[str, str]:
        """Return (url, service_role_key) or raise a clear error if missing."""
        if not self.supabase_url or not self.supabase_service_role_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in your .env file. "
                "Copy .env.example to .env and fill them in from your Supabase project settings."
            )
        return self.supabase_url, self.supabase_service_role_key.get_secret_value()

    def require_openrouter(self) -> str:
        """Return the OpenRouter API key, or raise a clear error if missing.

        Also requires CLAUDE_MODEL / OPENAI_MODEL / GEMINI_MODEL to be set
        explicitly — the app never silently falls back to a free model.
        """
        missing = [
            name
            for name, value in (
                ("OPENROUTER_API_KEY", self.openrouter_api_key),
                ("CLAUDE_MODEL", self.claude_model),
                ("OPENAI_MODEL", self.openai_model),
                ("GEMINI_MODEL", self.gemini_model),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"Missing required settings for LLM research: {', '.join(missing)}. "
                "Set them in your .env file."
            )
        return self.openrouter_api_key.get_secret_value()

    def require_assessment(self) -> tuple[str, dict[str, str]]:
        """Returns (api_key, {provider_name: model_slug}) for 3d, or raises
        if the key is missing or no assessment models are configured."""
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY must be set in your .env file to run --with-assessment."
            )
        models = self.get_assessment_models()
        if not models:
            raise RuntimeError(
                "No assessment models configured. Set CLAUDE_MODEL/OPENAI_MODEL/GEMINI_MODEL "
                "(reused by default) or OPENROUTER_ASSESSMENT_MODELS explicitly."
            )
        return self.openrouter_api_key.get_secret_value(), models


@lru_cache
def get_settings() -> Settings:
    return Settings()
