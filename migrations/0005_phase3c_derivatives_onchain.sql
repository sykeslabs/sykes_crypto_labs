-- Phase 3c: derivatives (funding, open interest, term structure, options,
-- CME positioning), on-chain/DeFi, and stablecoin-supply evidence.
--
-- Rather than one dedicated table per source (7+ nearly-identical tables for
-- what are mostly small, heterogeneous observations), this sub-phase
-- introduces ONE reusable table following 3a's evidence-provenance shape
-- exactly, with a JSONB payload for source-specific fields. This is the
-- generalization 3a's shape was designed for — `market_snapshots`/`news`/
-- `screened_universe` have stable, well-known column sets and stay as
-- dedicated tables; funding rates, OI, options, COT, TVL, etc. are numerous
-- and structurally similar, which is exactly the "many small observations"
-- case the provenance shape targets. Every source stays independently
-- inspectable via the `source` column — nothing is blended together.
--
-- Idempotent — safe to re-run.

create table if not exists evidence_observations (
    id                      uuid primary key default gen_random_uuid(),
    -- e.g. 'binance_funding_rate', 'deribit_options_iv', 'cftc_cot',
    -- 'defillama_tvl', 'defillama_stablecoin_supply'
    source                  text not null,
    asset_id                uuid references assets(id) on delete cascade,
    scope                   text not null check (scope in ('ASSET', 'GLOBAL_CRYPTO', 'MACRO')),
    observation_timestamp   timestamptz not null,
    publication_timestamp   timestamptz,
    retrieval_timestamp     timestamptz not null default now(),
    timeframe               text,
    -- Point-in-time integrity (3a): a provider's later correction is a new
    -- row linked to the one it corrects, never an UPDATE.
    is_revision_of          uuid references evidence_observations(id),
    freshness               text check (freshness in ('REALTIME', 'RECENT', 'STALE', 'UNKNOWN')),
    decay_half_life_hours   numeric,
    status                  text not null check (status in ('OK', 'UNAVAILABLE', 'UNKNOWN')),
    payload                 jsonb not null default '{}',
    created_at              timestamptz not null default now()
);

create index if not exists idx_evidence_observations_source_asset_retrieval
    on evidence_observations (source, asset_id, retrieval_timestamp desc);

create index if not exists idx_evidence_observations_source_observation
    on evidence_observations (source, observation_timestamp desc);
