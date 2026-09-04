-- Phase 1: asset universe + market data snapshots.
-- Apply via the Supabase SQL Editor, or scripts/apply_migration.py (see README).
-- Idempotent — safe to re-run against a database that already has this applied.

create extension if not exists "pgcrypto";

create table if not exists assets (
    id              uuid primary key default gen_random_uuid(),
    symbol          text not null unique,
    name            text not null,
    coingecko_id    text not null unique,
    active          boolean not null default true,
    -- Whether this asset is currently held in the live portfolio (vs. tracked
    -- for research/watchlist purposes only).
    in_asset        boolean not null default false,
    created_at      timestamptz not null default now()
);

alter table assets
    add column if not exists in_asset boolean not null default false;

create table if not exists market_snapshots (
    id                  uuid primary key default gen_random_uuid(),
    asset_id            uuid not null references assets(id) on delete cascade,
    timestamp           timestamptz not null,
    price               numeric not null,
    market_cap          numeric,
    volume_24h          numeric,
    price_change_24h    numeric,
    price_change_7d     numeric,
    price_change_30d    numeric,
    source              text not null default 'coingecko',
    created_at          timestamptz not null default now(),
    -- Safety net against exact-timestamp duplicate writes; the application
    -- layer also enforces a minimum interval between snapshots per asset.
    unique (asset_id, timestamp)
);

create index if not exists idx_market_snapshots_asset_timestamp
    on market_snapshots (asset_id, timestamp desc);

create index if not exists idx_assets_active
    on assets (active);

-- Seed the configurable asset universe (idempotent). CoinGecko ids for the
-- non-obvious tokens were verified against CoinGecko's /search endpoint to
-- avoid pointing at a wrong/similarly-named token.
insert into assets (symbol, name, coingecko_id, active, in_asset) values
    ('BTC',   'Bitcoin',     'bitcoin',                true, true),
    ('ETH',   'Ethereum',    'ethereum',               true, true),
    ('SOL',   'Solana',      'solana',                 true, false),
    ('XRP',   'XRP',         'ripple',                 true, false),
    ('BNB',   'BNB',         'binancecoin',            true, false),
    ('HYPE',  'Hyperliquid', 'hyperliquid',            true, false),
    ('LINK',  'Chainlink',   'chainlink',              true, true),
    ('ONDO',  'Ondo',        'ondo-finance',           true, true),
    ('JASMY', 'JasmyCoin',   'jasmycoin',              true, true),
    ('ENA',   'Ethena',      'ethena',                 true, true),
    ('S',     'Sonic',       'sonic-3',                true, true),
    ('STORJ', 'Storj',       'storj',                  true, true),
    ('ZRX',   '0x Protocol', '0x',                     true, true),
    ('XTZ',   'Tezos',       'tezos',                  true, true),
    ('BONK',  'Bonk',        'bonk',                   true, true),
    ('JTO',   'Jito',        'jito-governance-token',  true, true)
on conflict (symbol) do update set in_asset = excluded.in_asset;
