-- Phase 3e: Judge/Risk/Portfolio persistence groundwork. `judge_decisions`,
-- `decision_outcomes`, and `calibration_runs` already exist from 3a (reserved
-- empty specifically for this sub-phase) — nothing to add there. What 3a did
-- NOT anticipate is any numeric record of *current* portfolio state:
-- `assets.in_asset` is a plain boolean (held vs. not) with no allocation
-- size, and no prior sub-phase tracks one. Portfolio Construction (task 3)
-- needs a real "current allocation per asset" to size replacement decisions
-- against, and the Risk Engine's MAX_WEEKLY_TURNOVER cap (task 2) needs a
-- history of allocation changes to sum over a trailing window. Both are
-- genuinely new tables, not populated groundwork from 3a.
-- Idempotent — safe to re-run.

-- Current state of the paper book: one row per asset that has ever been
-- assigned a nonzero allocation by Portfolio Construction. No seed data —
-- Phase 1/2's `in_asset` flag was never a sized position, so the honest
-- starting state for every asset is "no position yet" until the first live
-- Judge/Risk/Portfolio run establishes one.
create table if not exists portfolio_positions (
    asset_id            uuid primary key references assets(id) on delete cascade,
    current_allocation  numeric not null default 0,
    last_decision_id    uuid references judge_decisions(id),
    updated_at          timestamptz not null default now()
);

-- Append-only log of every allocation change Portfolio Construction makes —
-- same "history table over a mutable column" pattern as 3a's
-- `asset_status_history`. This is what MAX_WEEKLY_TURNOVER sums over a
-- trailing window; `portfolio_positions` alone (current state only) can't
-- answer "how much changed in the last 7 days."
create table if not exists portfolio_allocation_changes (
    id                    uuid primary key default gen_random_uuid(),
    asset_id              uuid not null references assets(id) on delete cascade,
    run_id                text not null,
    decision_id           uuid references judge_decisions(id),
    previous_allocation   numeric not null,
    new_allocation        numeric not null,
    changed_at            timestamptz not null default now()
);

create index if not exists idx_portfolio_allocation_changes_changed_at
    on portfolio_allocation_changes (changed_at desc);

create index if not exists idx_portfolio_allocation_changes_asset
    on portfolio_allocation_changes (asset_id, changed_at desc);
