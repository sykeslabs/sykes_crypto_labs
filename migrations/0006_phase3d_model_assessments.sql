-- Phase 3d: multi-model current market assessment — a new, parallel evidence
-- type, distinct from Phase 2's `llm_analyses`. Idempotent — safe to re-run.

create table if not exists model_market_assessments (
    id                       uuid primary key default gen_random_uuid(),
    run_id                   text not null,
    asset_id                 uuid not null references assets(id) on delete cascade,
    provider                 text not null,
    model                    text not null,
    prompt_template_id       uuid references prompt_templates(id),
    assessment_timestamp     timestamptz not null,
    -- The latest instant any evidence fed into this assessment's context was
    -- retrieved — the no-lookahead boundary for this row (mirrors Phase 2's
    -- news `as_of` cutoff, generalized to every evidence type in the prompt).
    data_cutoff_timestamp    timestamptz not null,
    short_term_direction     text check (short_term_direction in ('BULLISH', 'NEUTRAL', 'BEARISH')),
    medium_term_direction    text check (medium_term_direction in ('BULLISH', 'NEUTRAL', 'BEARISH')),
    long_term_direction      text check (long_term_direction in ('BULLISH', 'NEUTRAL', 'BEARISH')),
    short_term_confidence    numeric check (short_term_confidence between 0 and 1),
    medium_term_confidence   numeric check (medium_term_confidence between 0 and 1),
    long_term_confidence     numeric check (long_term_confidence between 0 and 1),
    expected_return_7d       numeric,
    expected_return_30d      numeric,
    expected_return_90d      numeric,
    risk_score               numeric check (risk_score between 0 and 1),
    risk_level               text check (risk_level in ('LOW', 'MEDIUM', 'HIGH')),
    -- Copied from the run's shared market_regime_snapshots row (3b), for
    -- convenience/auditability on this row — not independently inferred.
    market_regime            text,
    -- Computed once per asset per run across all configured models (a
    -- directional-agreement measure — see app/llm/assessment_service.py),
    -- then denormalized onto every model's row for that asset/run. Distinct
    -- from any individual model's confidence — never an average of it.
    model_agreement          numeric check (model_agreement between 0 and 1),
    overall_assessment       text check (overall_assessment in ('BULLISH', 'NEUTRAL', 'BEARISH')),
    thesis                   text,
    key_drivers              jsonb not null default '[]',
    key_risks                jsonb not null default '[]',
    source_assessment        jsonb not null default '[]',
    invalidation_conditions  jsonb not null default '[]',
    raw_response             jsonb,
    -- Per the CostGuard-extension convention (PHASE3_LOCKED_DECISIONS.md):
    -- registered in COST_TRACKED_TABLES (app/llm/cost.py).
    estimated_cost           numeric,
    created_at               timestamptz not null default now()
);

create index if not exists idx_model_market_assessments_run_id
    on model_market_assessments (run_id);

create index if not exists idx_model_market_assessments_asset_timestamp
    on model_market_assessments (asset_id, assessment_timestamp desc);
