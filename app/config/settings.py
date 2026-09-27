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

    # `env_ignore_empty=True`: a .env line present but set to an empty
    # string (e.g. "SEC_EDGAR_USER_AGENT=", left blank rather than deleted)
    # is treated the same as the var being absent entirely -- falls back to
    # the field's own Python default instead of literally using "". Real
    # bug found and fixed here: SEC_EDGAR_USER_AGENT="" was being sent
    # as-is to SEC EDGAR, which rejects an empty/generic User-Agent with a
    # 403 per its fair-access policy, silently overriding this class's own
    # safe non-empty default below. The same blank-but-present pattern
    # exists in this project's own .env for several other optional
    # settings (JUDGE_MODEL, ADVERSARIAL_MODEL, REASONING_AUDIT_MODEL,
    # OPENROUTER_ASSESSMENT_MODELS, and a few API keys) -- this fixes the
    # whole class of them, not just this one field.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    # Supabase (required)
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None

    # CoinGecko (optional — falls back to public unauthenticated endpoint)
    coingecko_api_key: SecretStr | None = None
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"

    # Only used by scripts/apply_migration.py, not by the core app.
    database_url: str | None = None

    # Phase 5: the read/query API's single access-control gate (localhost/
    # personal-machine scope only — see README's Phase 5 section).
    x_api_key: SecretStr | None = None

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
    # Real incident 2026-09-18: Gemini 2.5 Pro (via OpenRouter) entered a
    # degenerate, repetitive internal "thinking" loop on a real research
    # call (~1700+ completion tokens of near-duplicate reasoning text,
    # never reaching an actual answer) and the request eventually failed
    # with an upstream idle timeout after several minutes, at real cost.
    # OpenRouter's unified `reasoning.max_tokens` parameter maps directly to
    # Gemini's native `thinkingBudget` (0-24576 for the 2.5 series; Pro
    # cannot fully disable thinking the way Flash can with 0). Passed only
    # for the gemini provider in the research/assessment stages -- an
    # explicit cap, not a validated-optimal value; revisit if it turns out
    # too small for genuine reasoning or doesn't actually prevent a repeat.
    gemini_reasoning_max_tokens: int = 4096
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
    # Raised 30 -> 50 (2026-09-13): the original reasoning above (CoinGecko's
    # free-tier per-asset historical endpoint rate-limiting after ~5 rapid
    # calls) no longer applies -- today's screening pipeline gets
    # volatility/drawdown from Binance/Coinbase klines instead (verified
    # live: 14 sequential klines calls completed in 3.7s with zero
    # rate-limiting), and CoinGecko/CoinMarketCap universe calls are single
    # batched requests regardless of size. Raising this mainly means more
    # sequential Binance/Coinbase OHLCV calls (longer real run time, not
    # more real dollar cost -- LLM spend is gated by top_candidates_size,
    # unchanged at 10) -- a real, verified decision, not the old
    # conservative default carried over out of habit.
    screening_universe_size: int = 50
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
    # Phase 3i: entity-flow intelligence (smart-money netflow). Free tier:
    # 100 one-time credits + 10/day refill — real, but credit-constrained
    # (see README's Phase 3i section). Without a key, ENTITY_FLOW_INTELLIGENCE
    # is recorded NOT_IMPLEMENTED, never approximated.
    nansen_api_key: SecretStr | None = None
    nansen_base_url: str = "https://api.nansen.ai/api/v1"
    # Optional. A free GitHub personal access token raises the rate limit
    # from 60/hr to 5000/hr for developer-activity commit/contributor
    # lookups — not required for a small TOP_CANDIDATES-sized universe.
    github_token: SecretStr | None = None
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
    # v2 (2026-09-12): added an explicit instruction to flag/discount any
    # claim not traceable to this run's own evidence as an unverified prior
    # rather than a confirmed fact -- a direct mitigation for a confirmed
    # LLM parametric-knowledge-leakage finding (see README/dashboard TODO:
    # a real backfilled decision cited a real 2025 narrative as active in
    # 2024, then admitted in its own output that it wasn't evidence-backed).
    assessment_prompt_version: str = "v2"

    # Judge (Phase 3e, used only with --with-judge). A single synthesizing
    # model — unlike 3d's independent ensemble, the Judge is one reasoning
    # step over already-independent evidence (including 3d's ensemble
    # itself). Defaults to reusing CLAUDE_MODEL unless overridden.
    judge_model: str | None = None
    # v3 (2026-09-12): same unverified-prior mitigation as
    # assessment_prompt_version v2 above, applied to the Judge's own
    # synthesis step too.
    judge_prompt_version: str = "v3"

    # Risk Engine (Phase 3e, used only with --with-judge). Deterministic,
    # configurable hard gates over the Judge's unconstrained output — see
    # PHASE3E_PROMPT.md task 2. Defaults are conservative starting points for
    # a paper system, not backtested-optimal values.
    max_single_asset_allocation: float = 0.15
    max_new_position_size: float = 0.05
    # POLICY (real bug fixed + pre-production-audited 2026-09-14/15, see
    # app/risk/engine.py's RiskEngine._strategy_turnover_delta docstring for
    # the full incident): turnover is measured from the previous SYSTEM
    # TARGET to the new system target, never from real holdings. Actual
    # holdings remain the sole source of truth for real portfolio risk and
    # position state (every real gating decision -- is_new_position, the
    # rebalance-confidence bar, WATCH's "hold what you actually have" --
    # still uses them, unchanged) -- but an externally-caused change in
    # actual holdings (a manual `/holdings` trade, a price move) is NOT
    # strategy turnover and is never charged against this budget.
    #
    # This 30% figure is a circuit breaker against excessive STRATEGY
    # TARGET CHURN -- a real transaction-cost analysis (147 resolved
    # decisions, 2026-09-14) found average net-of-costs drag of only
    # ~0.26pp/decision, too small to justify a cost-optimization-based cap
    # at any particular size. Do NOT read 30%/7-days as empirically
    # optimal: a 2026-09-15 backtest across 7/14/30-day windows and
    # multiple budgets found this project's ~10 days of real history
    # insufficient to distinguish between them, and an earlier ~30-day/
    # 60-75% hypothesis was tested and found WORSE for the one real
    # incident it was meant to address -- this value is kept because no
    # evidence yet supports changing it, not because it's been validated
    # as correct.
    max_weekly_turnover: float = 0.30
    min_buy_confidence: float = 0.55
    min_rebalance_confidence: float = 0.50
    min_sell_confidence: float = 0.50
    # A new candidate must beat the weakest existing holding's own
    # risk_adjusted_alpha by at least this margin before it's allowed to
    # replace it (app/portfolio/construction.py's replacement rule) --
    # a hysteresis/switching-cost buffer, not a backtested-optimal value:
    # without it, a candidate only marginally better than an existing
    # holding would keep displacing it every run, generating real turnover/
    # fee cost (see app/trading/fill_simulator.py) for a negligible expected
    # alpha gain. 0.03 (3 percentage points of risk_adjusted_alpha) is a
    # documented convention, chosen the same way COMPOSITE_FACTOR_WEIGHTS
    # was (app/market_data/factors.py) -- not fit or backtested against
    # real turnover-adjusted outcomes. Sensitivity-test once enough resolved
    # decisions exist across enough replacement events to compare this
    # value against alternatives (see the dashboard's own TODO).
    min_replacement_alpha_advantage: float = 0.03
    # Portfolio Construction's replacement rule (task 3) only has teeth once
    # there's a real capacity limit — otherwise every new candidate could
    # just be added indefinitely. A conservative starting cap, not a
    # backtested-optimal value. Same documented-convention-not-backtested
    # status as min_replacement_alpha_advantage above -- see the dashboard's
    # own TODO.
    max_concurrent_positions: int = 8
    # Baseline daily-return stdev used as the reference point for the
    # inverse-volatility position-sizing scalar (task 2) — an asset at
    # exactly this volatility gets no scale-up/down; more volatile assets
    # scale down, less volatile assets are capped at no scale-up (this is a
    # risk-reduction mechanism, not a leverage mechanism).
    risk_target_volatility: float = 0.03
    # Two assets' 30d daily-return correlation at/above this is treated as
    # "concentrated" by the correlation-awareness flag (task 2).
    correlation_flag_threshold: float = 0.7
    # Phase 3h task 2: a candidate/current portfolio whose estimated stress-
    # scenario drawdown (magnitude) exceeds this is FLAGGED in output/logs,
    # same reporting-only standing as `requires_review` — never blocks
    # Portfolio Construction in this sub-phase.
    max_stress_scenario_drawdown: float = 0.5

    # Phase 5o (2026-09-27): a real position worth less than this (USD,
    # current value) is dust, not a real holding to actively manage —
    # found live: 15 positions from years of tiny staking rewards, ranging
    # $0.0000000000-$0.062, were forcing Judge coverage (real LLM cost
    # spent asking "should I trade $0.00 of REN") and cluttering My
    # Portfolio with 0.00%-allocation rows. $1 sits well inside the real
    # observed gap between the largest dust position (JTO, $0.062) and the
    # smallest genuine holding (BONK, $15.58) at the time this was chosen.
    # Applied at `_get_held_assets()` (Judge/screening coverage),
    # `GET /holdings` (display), and `reconcile_in_asset.py` (`in_asset`) —
    # deliberately NOT applied to market-data collection, which stays
    # free/harmless to run for every real position regardless of size.
    min_material_holding_usd: float = 1.0

    # Adversarial research, macro matrix, remaining fragile sources (Phase 3f,
    # used only with --with-adversarial / --with-macro)
    # A single model does the whole bull -> bear -> scenario research cycle
    # (unlike 3d's independent ensemble) — defaults to reusing CLAUDE_MODEL.
    adversarial_model: str | None = None
    reasoning_audit_model: str | None = None
    adversarial_prompt_version: str = "v1"
    # FRED (Federal Reserve Economic Data). Optional — free signup. Without a
    # key, GLOBAL_LIQUIDITY_MACRO is reported NOT_IMPLEMENTED, never approximated.
    fred_api_key: SecretStr | None = None
    fred_base_url: str = "https://api.stlouisfed.org/fred"
    # congress.gov (legislative tracking, one half of the regulatory/policy
    # event calendar). Optional — free signup. SEC EDGAR's full-text search
    # (the other half) needs no key at all.
    congress_gov_api_key: SecretStr | None = None
    congress_gov_base_url: str = "https://api.congress.gov/v3"
    sec_edgar_base_url: str = "https://efts.sec.gov/LATEST"
    # A descriptive User-Agent is required by SEC's fair-access policy — not
    # a secret, just identifies the requester.
    sec_edgar_user_agent: str = "sykeslabs"
    upbit_base_url: str = "https://api.upbit.com/v1"
    santiment_base_url: str = "https://api.santiment.net/graphql"

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

    def require_judge(self) -> tuple[str, str]:
        """Returns (api_key, model) for 3e's Judge, or raises if missing."""
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY must be set in your .env file to run --with-judge."
            )
        model = self.judge_model or self.claude_model
        if not model:
            raise RuntimeError(
                "No Judge model configured. Set JUDGE_MODEL (or CLAUDE_MODEL, reused by default) "
                "in your .env file."
            )
        return self.openrouter_api_key.get_secret_value(), model

    def require_adversarial(self) -> tuple[str, str]:
        """Returns (api_key, model) for 3f's bull/bear/scenario research
        cycle, or raises if missing."""
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY must be set in your .env file to run --with-adversarial."
            )
        model = self.adversarial_model or self.claude_model
        if not model:
            raise RuntimeError(
                "No adversarial-research model configured. Set ADVERSARIAL_MODEL (or "
                "CLAUDE_MODEL, reused by default) in your .env file."
            )
        return self.openrouter_api_key.get_secret_value(), model

    def require_reasoning_audit(self) -> tuple[str, str]:
        """Returns (api_key, model) for 3g's Judge reasoning audit, or
        raises if missing."""
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY must be set in your .env file to run scripts/run_reasoning_audit.py."
            )
        model = self.reasoning_audit_model or self.claude_model
        if not model:
            raise RuntimeError(
                "No reasoning-audit model configured. Set REASONING_AUDIT_MODEL (or "
                "CLAUDE_MODEL, reused by default) in your .env file."
            )
        return self.openrouter_api_key.get_secret_value(), model

    def require_x_api_key(self) -> str:
        """Phase 5: the single configured API key gating every read/query
        endpoint except the health check. Localhost/personal-machine scope
        only (see doc/phases.md's Phase 5 section) — this is a genuinely
        sufficient minimum bar for that scope, not a stand-in for
        production auth."""
        if not self.x_api_key:
            raise RuntimeError(
                "X_API_KEY must be set in your .env file to run the Phase 5 API "
                "(app.api.main) — do not ship an unauthenticated read layer, even for "
                "a personal/paper-only, localhost-only deployment."
            )
        return self.x_api_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
