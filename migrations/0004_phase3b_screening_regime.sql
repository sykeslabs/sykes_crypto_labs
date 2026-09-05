-- Phase 3b: CoinMarketCap identifier, screened-universe persistence.
-- No changes to market_regime_snapshots' shape (already created in 3a) —
-- this sub-phase only starts populating it.
-- Idempotent — safe to re-run.

-- Parallel to the existing coingecko_id: kept independent, never merged with
-- it, so cross-source disagreement between CoinGecko and CoinMarketCap stays
-- visible rather than being silently resolved to one value.
alter table assets
    add column if not exists coinmarketcap_id text;

create unique index if not exists idx_assets_coinmarketcap_id
    on assets (coinmarketcap_id)
    where coinmarketcap_id is not null;

-- The full screened universe for a run (task 9) — one row per screened
-- asset, not just the ones that surface as TOP_CANDIDATES, so 3g can later
-- check for survivorship bias in discovery. `asset_id` is nullable and only
-- populated once/if the symbol corresponds to a row in `assets` (an existing
-- held/watchlist asset, or a newly-promoted candidate) — most of a 30-asset
-- screening universe will never become a tracked asset, and requiring an
-- `assets` row for every screened symbol would pollute that table with
-- one-off entries that are never candidates again.
create table if not exists screened_universe (
    id                      uuid primary key default gen_random_uuid(),
    run_id                  text not null,
    computed_at             timestamptz not null default now(),
    symbol                  text not null,
    coingecko_id            text,
    coinmarketcap_id        text,
    asset_id                uuid references assets(id) on delete set null,
    rank                    integer,
    market_cap              numeric,
    volume_24h              numeric,
    momentum_7d             numeric,
    momentum_30d            numeric,
    -- Sourced from Binance first, Coinbase as fallback (both provide daily
    -- OHLCV with no rate-limit issues at this universe size); null/UNAVAILABLE
    -- only if neither venue lists the asset — never approximated from a
    -- point-return percentage.
    volatility_30d          numeric,
    drawdown_30d            numeric,
    volatility_drawdown_source  text check (volatility_drawdown_source in ('BINANCE', 'COINBASE', 'UNAVAILABLE')),
    relative_strength_30d   numeric,
    composite_factor_score  numeric,
    anomaly_flag            boolean not null default false,
    anomaly_reason          text,
    is_top_candidate        boolean not null default false,
    -- Per-source raw prices for this run, so cross-source disagreement stays
    -- independently inspectable rather than collapsed into one number.
    source_prices           jsonb not null default '{}',
    created_at              timestamptz not null default now()
);

create index if not exists idx_screened_universe_run_id
    on screened_universe (run_id);

create index if not exists idx_screened_universe_symbol_computed
    on screened_universe (symbol, computed_at desc);

create index if not exists idx_screened_universe_top_candidates
    on screened_universe (run_id, is_top_candidate);
