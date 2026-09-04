-- Phase 2: news collection + multi-model LLM analyses.
-- Apply via the Supabase SQL Editor, or scripts/apply_migration.py.
-- Idempotent — safe to re-run.

create table if not exists news (
    id                  uuid primary key default gen_random_uuid(),
    published_at        timestamptz not null,
    source              text not null,
    title               text not null,
    url                 text not null,
    summary             text,
    sentiment           text,
    -- Asset symbols this article was matched to (e.g. {'BTC','ETH'}).
    relevant_assets     text[] not null default '{}',
    -- sha256(title + url), enforced unique to prevent re-storing the same article.
    content_hash        text not null unique,
    created_at          timestamptz not null default now()
);

create index if not exists idx_news_published_at
    on news (published_at desc);

create index if not exists idx_news_relevant_assets
    on news using gin (relevant_assets);

create table if not exists llm_analyses (
    id                          uuid primary key default gen_random_uuid(),
    run_id                      text not null,
    asset_id                    uuid not null references assets(id) on delete cascade,
    provider                    text not null,
    model                       text not null,
    prompt_version              text not null,
    timestamp                   timestamptz not null default now(),
    -- sha256 of the exact research context sent to the model, for auditability.
    input_hash                  text not null,
    response                    jsonb not null,
    action                      text not null check (action in ('BUY', 'HOLD', 'SELL')),
    confidence                  numeric not null check (confidence >= 0 and confidence <= 1),
    target_allocation           numeric,
    investment_horizon          text,
    bull_case                   text,
    bear_case                   text,
    catalysts                   text[] not null default '{}',
    risks                       text[] not null default '{}',
    invalidation_conditions     text[] not null default '{}',
    token_usage                 jsonb,
    estimated_cost              numeric not null default 0,
    created_at                  timestamptz not null default now()
);

create index if not exists idx_llm_analyses_run_id
    on llm_analyses (run_id);

create index if not exists idx_llm_analyses_asset_timestamp
    on llm_analyses (asset_id, timestamp desc);

create index if not exists idx_llm_analyses_timestamp
    on llm_analyses (timestamp desc);
