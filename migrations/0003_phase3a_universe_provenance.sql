-- Phase 3a: candidate/portfolio status history, signal-source registry, and
-- empty schema groundwork for market-regime classification (3b), the Judge
-- and its decision-outcome ledger (3e), prompt/template versioning (3d),
-- and calibration-attempt tracking (3e/3g).
--
-- No new external API calls, no new LLM calls, no behavior change to any
-- existing Phase 1/2 code path. Idempotent — safe to re-run.

-- =============================================================================
-- 1. Candidate/portfolio status (auditable history, not a column)
-- =============================================================================
-- `assets.active`/`assets.in_asset` are untouched. This is a separate,
-- append-only history of HELD/WATCHLIST/CANDIDATE/REJECTED status changes —
-- chosen over a single column so status transitions stay auditable once 3b's
-- candidate discovery starts moving assets between these states. The
-- "current" status for an asset is the row with the latest `changed_at`.
create table if not exists asset_status_history (
    id          uuid primary key default gen_random_uuid(),
    asset_id    uuid not null references assets(id) on delete cascade,
    status      text not null check (status in ('HELD', 'WATCHLIST', 'CANDIDATE', 'REJECTED')),
    reason      text,
    changed_at  timestamptz not null default now(),
    created_at  timestamptz not null default now()
);

create index if not exists idx_asset_status_history_asset_changed
    on asset_status_history (asset_id, changed_at desc);

-- Seed one row per existing asset from its current `in_asset` flag, so the
-- history table isn't empty/ambiguous for assets that already exist.
insert into asset_status_history (asset_id, status, reason, changed_at)
select
    id,
    case when in_asset then 'HELD' else 'WATCHLIST' end,
    'Seeded from existing in_asset flag during Phase 3a migration',
    now()
from assets
where not exists (
    select 1 from asset_status_history h where h.asset_id = assets.id
);

-- =============================================================================
-- 2. Signal source registry
-- =============================================================================
create table if not exists signal_sources (
    name            text primary key,
    enabled         boolean not null default true,
    status          text not null default 'NOT_IMPLEMENTED'
                        check (status in ('OK', 'UNAVAILABLE', 'UNKNOWN', 'NOT_IMPLEMENTED')),
    last_checked_at timestamptz,
    notes           text,
    created_at      timestamptz not null default now()
);

-- Seeded once; `on conflict do nothing` so a later re-run never clobbers an
-- operator's manual status update (e.g. once a source is actually verified).
insert into signal_sources (name, enabled, status, notes) values
    ('CoinGecko', true, 'OK', 'Phase 1 — aggregated price/market-cap data, already implemented'),
    ('News', true, 'OK', 'Phase 2 — RSS news collection + relevance matching, already implemented'),
    ('CoinMarketCap', false, 'NOT_IMPLEMENTED', 'Aggregated price/market-cap data; built in 3b'),
    ('Coinbase', false, 'NOT_IMPLEMENTED', 'Exchange-native trade price/spread; built in 3b'),
    ('Binance', false, 'NOT_IMPLEMENTED', 'Exchange-native price/funding rate; built in 3b, 3c'),
    ('Deribit', false, 'NOT_IMPLEMENTED', 'Options implied volatility, put/call skew; built in 3c'),
    ('Etherscan', false, 'NOT_IMPLEMENTED', 'On-chain transfer-flow proxies; built in 3c'),
    ('DefiLlama', false, 'NOT_IMPLEMENTED', 'DeFi protocol TVL flows; built in 3c'),
    ('CoinAnk', false, 'NOT_IMPLEMENTED', 'Long/short ratio; fragile/unofficial, feasibility-gated in 3f'),
    ('CoinGlass', false, 'NOT_IMPLEMENTED', 'Liquidation heatmap; fragile/unofficial, feasibility-gated in 3f'),
    ('CryptoBubbles', false, 'NOT_IMPLEMENTED', 'Market-cap bubble visualization; fragile/unofficial, feasibility-gated in 3f'),
    ('PlanB', false, 'NOT_IMPLEMENTED', 'PlanB/X independent-analyst opinion; accessed via xAI/Grok, feasibility-gated in 3f'),
    ('Macro', false, 'NOT_IMPLEMENTED', 'Macro evidence matrix; built in 3f'),
    ('AGGREGATE_OPEN_INTEREST', false, 'NOT_IMPLEMENTED', 'Binance/Deribit futures open interest, distinct from funding rate; built in 3c'),
    ('STABLECOIN_SUPPLY_VELOCITY_AND_EXCHANGE_RESERVES', false, 'NOT_IMPLEMENTED', 'Stablecoin supply growth/velocity + exchange reserves, capital-rotation proxy; built in 3c'),
    ('SPOT_ETF_FLOWS', false, 'NOT_IMPLEMENTED', 'Daily net spot BTC/ETH ETF flows via an aggregator (Farside/SoSoValue); built in 3c'),
    ('PREDICTION_MARKETS', false, 'NOT_IMPLEMENTED', 'Implied probabilities for macro/crypto event contracts (Polymarket/Kalshi); built in 3c'),
    ('ON_CHAIN_VALUATION_METRICS', false, 'NOT_IMPLEMENTED', 'MVRV/MVRV Z-Score, SOPR, NUPL, LTH/STH-MVRV cohorts (Glassnode/CryptoQuant-class); built in 3c'),
    ('FUTURES_TERM_STRUCTURE', false, 'NOT_IMPLEMENTED', 'Dated-futures basis/contango-backwardation curve; built in 3c'),
    ('TOKEN_UNLOCK_SCHEDULE', false, 'NOT_IMPLEMENTED', 'Vesting/unlock calendar (Messari/TokenUnlocks-class); built in 3c'),
    ('SOCIAL_NARRATIVE_SENTIMENT', false, 'NOT_IMPLEMENTED', 'Social volume/trending-narrative rotation (Santiment/LunarCrush-class); fragile, feasibility-gated in 3f'),
    ('CME_COT_POSITIONING', false, 'NOT_IMPLEMENTED', 'CFTC Commitment of Traders report for CME BTC/ETH futures; built in 3c'),
    ('ON_CHAIN_MINER_METRICS', false, 'NOT_IMPLEMENTED', 'BTC hash rate, difficulty, miner reserves/flows; built in 3c'),
    ('GLOBAL_LIQUIDITY_MACRO', false, 'NOT_IMPLEMENTED', 'FRED M2/Fed balance sheet/reverse repo + cross-asset correlation; built in 3f'),
    ('REGULATORY_EVENT_CALENDAR', false, 'NOT_IMPLEMENTED', 'Dated regulatory/policy catalysts (SEC EDGAR, congress.gov); extraction-gated in 3f'),
    ('REGIONAL_EXCHANGE_PREMIUM', false, 'NOT_IMPLEMENTED', 'Structural cross-region price divergence (e.g. Kimchi premium); fragile, feasibility-gated in 3f'),
    ('ENTITY_FLOW_INTELLIGENCE', false, 'NOT_IMPLEMENTED', 'Wallet-entity-clustering / "smart money" flow tracking (Nansen/Arkham-class); built in 3i'),
    ('CUSTODY_OTC_FLOW', false, 'NOT_IMPLEMENTED', 'Custody/OTC-desk balance/flow tracking; built in 3i'),
    ('NETWORK_FUNDAMENTALS_DEV_ACTIVITY', false, 'NOT_IMPLEMENTED', 'Network usage + developer/build-activity fundamentals; built in 3i')
on conflict (name) do nothing;

-- =============================================================================
-- 3. Schema groundwork for later sub-phases (structure only, not populated)
-- =============================================================================

-- 3b's deterministic market-regime classifier, computed once per run.
-- `regime` is intentionally left as free text rather than a check-constrained
-- enum: 3b defines the actual label set (suggested: RISK_ON/RISK_OFF/NEUTRAL)
-- and may need to refine it without another migration.
create table if not exists market_regime_snapshots (
    id          uuid primary key default gen_random_uuid(),
    run_id      text not null,
    computed_at timestamptz not null default now(),
    regime      text,
    inputs      jsonb not null default '{}',
    notes       text
);

create index if not exists idx_market_regime_snapshots_computed_at
    on market_regime_snapshots (computed_at desc);

-- Prompt/template versioning, starting in 3d.
create table if not exists prompt_templates (
    id             uuid primary key default gen_random_uuid(),
    name           text not null,
    stage          text not null,
    version        text not null,
    template_hash  text not null,
    created_at     timestamptz not null default now(),
    unique (name, stage, version)
);

-- The full Judge decision record (3e populates it). Reserved now so
-- decision_outcomes.decision_id below has a real FK target instead of a
-- placeholder. `decision` is constrained to the DecisionValue vocabulary
-- introduced in this sub-phase (see app/judge/decisions.py) — this is the
-- concrete, enforced home for BUY/HOLD/SELL/WATCH/NO_TRADE; no decision
-- logic is built yet, only the value space.
create table if not exists judge_decisions (
    id                       uuid primary key default gen_random_uuid(),
    run_id                   text not null,
    asset_id                 uuid not null references assets(id) on delete cascade,
    created_at               timestamptz not null default now(),
    decision                 text check (decision in ('BUY', 'HOLD', 'SELL', 'WATCH', 'NO_TRADE')),
    confidence               numeric,
    target_allocation        numeric,
    expected_return          numeric,
    expected_alpha           numeric,
    risk_score               numeric,
    uncertainty              numeric,
    model_agreement          numeric,
    source_agreement         numeric,
    investment_horizon_days  integer,
    key_evidence             jsonb,
    contradictory_evidence   jsonb,
    key_risks                jsonb,
    invalidation_conditions  jsonb,
    requires_review          boolean not null default false,
    thesis                   text,
    regime_id                uuid references market_regime_snapshots(id),
    prompt_template_id       uuid references prompt_templates(id),
    -- Per the CostGuard-extension convention (PHASE3_LOCKED_DECISIONS.md):
    -- every LLM-call-persisting table has an `estimated_cost` column and is
    -- added to COST_TRACKED_TABLES when it starts being populated (3e).
    estimated_cost           numeric
);

create index if not exists idx_judge_decisions_run_id
    on judge_decisions (run_id);

create index if not exists idx_judge_decisions_asset_created
    on judge_decisions (asset_id, created_at desc);

-- 3e's continuous calibration ledger.
create table if not exists decision_outcomes (
    id                  uuid primary key default gen_random_uuid(),
    decision_id         uuid not null references judge_decisions(id) on delete cascade,
    asset_id            uuid not null references assets(id) on delete cascade,
    decision_timestamp  timestamptz not null,
    horizon_days        integer,
    target_return       numeric,
    stop_return         numeric,
    realized_return     numeric,
    outcome_label       text check (outcome_label in ('HIT_TARGET', 'HIT_STOP', 'TIMED_OUT', 'UNRESOLVED')),
    evaluated_at        timestamptz,
    -- Denormalized for cheap per-regime accuracy breakdowns later (3g).
    regime_at_decision  uuid references market_regime_snapshots(id),
    -- Denormalized from the Judge decision row so calibration queries don't
    -- need to join back through judge_decisions for this one field.
    judge_confidence    numeric,
    -- Marks a decision as never touched during iteration — the only slice
    -- later sub-phases (3g) may honestly call "out of sample."
    in_holdout_window   boolean not null default false
);

create index if not exists idx_decision_outcomes_asset_id
    on decision_outcomes (asset_id);

create index if not exists idx_decision_outcomes_decision_id
    on decision_outcomes (decision_id);

-- Tracks calibration/backtest *attempts* as first-class, countable events —
-- starting with 3e's baseline script, extended by 3g. Exists as its own
-- table (rather than being inferred after the fact) because correcting for
-- how many times a prompt/logic change was tried and re-evaluated
-- (multiple-comparisons bias) requires an honest count of attempts, not just
-- a count of resolved decisions.
create table if not exists calibration_runs (
    id                  uuid primary key default gen_random_uuid(),
    run_at              timestamptz not null default now(),
    method              text,
    sample_size         integer,
    prompt_template_ids jsonb not null default '[]',
    hit_rate            numeric,
    brier_score         numeric,
    notes               text
);

-- =============================================================================
-- Evidence provenance shape (convention, not a standalone table)
-- =============================================================================
-- Every future evidence-source table (3b, 3c, 3f) is expected to include
-- these columns alongside its own source-specific fields — see
-- app/database/evidence_provenance.py for the Python-side shared shape,
-- decay-half-life reference values, and the "value as known at time T"
-- query helper:
--
--   source                    text
--   asset_id                  uuid, nullable (null for GLOBAL_CRYPTO/MACRO scope)
--   scope                     text: ASSET / GLOBAL_CRYPTO / MACRO
--   observation_timestamp     timestamptz
--   publication_timestamp     timestamptz, nullable
--   retrieval_timestamp       timestamptz
--   timeframe                 text, nullable
--   is_revision_of            <self-FK>, nullable — a provider's later
--                             correction is a NEW row linked to the one it
--                             corrects, never an UPDATE overwriting the
--                             originally-retrieved value (point-in-time
--                             integrity — see PHASE3A_PROMPT.md).
--   freshness                 text: REALTIME / RECENT / STALE / UNKNOWN
--   decay_half_life_hours     numeric, per source *type*, not per observation
--   status                    text: OK / UNAVAILABLE / UNKNOWN
--   payload                   jsonb, source-specific fields
--
-- "Value as known at time T" query convention: the latest row for a given
-- (source, asset_id) ordered by retrieval_timestamp where
-- retrieval_timestamp <= T. Because a correction is always a new row with
-- its own (later) retrieval_timestamp, this ordering alone resolves "what
-- was known then" correctly without needing to walk the is_revision_of
-- chain by hand. Example against any concrete future table:
--
--   select * from <evidence_table>
--   where source = :source and asset_id = :asset_id
--     and retrieval_timestamp <= :as_of
--   order by retrieval_timestamp desc
--   limit 1;

-- =============================================================================
-- Note for 3b (no action taken here — informational only)
-- =============================================================================
-- Whatever table 3b uses to persist the full screened universe should
-- reserve a `composite_factor_score` (numeric, nullable) column now, even
-- though it isn't computed until 3b. This is a deterministic, non-LLM
-- composite of 3b's own screening factors (momentum, volatility, drawdown,
-- relative strength) — it gives 3e's Judge a purely quantitative,
-- non-narrative input to compare against LLM/adversarial-research evidence,
-- without conflating the two into one blended number.
