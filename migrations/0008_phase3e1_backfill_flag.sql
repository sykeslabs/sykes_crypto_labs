-- Phase 3e.1: retroactive historical replay. A new column, not an edit to
-- any prior migration. Idempotent — safe to re-run.

alter table judge_decisions
    add column if not exists is_backfilled boolean not null default false;

alter table decision_outcomes
    add column if not exists is_backfilled boolean not null default false;

create index if not exists idx_judge_decisions_is_backfilled
    on judge_decisions (is_backfilled);

create index if not exists idx_decision_outcomes_is_backfilled
    on decision_outcomes (is_backfilled);
