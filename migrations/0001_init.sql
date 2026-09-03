-- Phase 1: asset universe + market data snapshots.
-- Apply via the Supabase SQL Editor, or scripts/apply_migration.py (see README).

create extension if not exists "pgcrypto";

create table if not exists assets (
    id              uuid primary key default gen_random_uuid(),
    symbol          text not null unique,
    name            text not null,
    coingecko_id    text not null unique,
    active          boolean not null default true,
    created_at      timestamptz not null default now()
);

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

-- Seed the initial configurable asset universe (idempotent).
insert into assets (symbol, name, coingecko_id, active) values
    ('BTC',  'Bitcoin',     'bitcoin',      true),
    ('ETH',  'Ethereum',    'ethereum',     true),
    ('SOL',  'Solana',      'solana',       true),
    ('XRP',  'XRP',         'ripple',       true),
    ('BNB',  'BNB',         'binancecoin',  true),
    ('HYPE', 'Hyperliquid', 'hyperliquid',  true)
on conflict (symbol) do nothing;
