-- Real, persisted, dashboard-visible record of every run where
-- MAX_WEEKLY_TURNOVER capped at least one proposed position change. Found
-- live 2026-09-14: before this, a fully-blocked run (every proposed change
-- reverted because the week's real turnover was already at/over budget)
-- was only ever logged via a stdout logger.warning -- never persisted,
-- never surfaced on the dashboard, and this project has no log file at
-- all, so it was completely invisible after the fact.
-- Idempotent -- safe to re-run.

create table if not exists turnover_cap_events (
    id uuid primary key default gen_random_uuid(),
    run_id text not null,
    occurred_at timestamptz not null,
    turnover_used_this_week numeric not null,
    max_weekly_turnover numeric not null,
    remaining_budget numeric not null,
    fully_blocked boolean not null,
    capped_symbols jsonb not null default '[]'::jsonb
);

create index if not exists idx_turnover_cap_events_occurred_at on turnover_cap_events (occurred_at desc);
