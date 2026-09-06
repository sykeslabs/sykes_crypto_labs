-- Phase 3g task 5: Judge reasoning audit. Formalizes 3f's manual spot-check
-- into a persisted, repeatable check — a single structured LLM call per
-- sampled decision, given only its stored key_evidence/contradictory_evidence
-- /thesis, flags whether the thesis is genuinely supported or contains an
-- unsupported leap. Idempotent — safe to re-run.

create table if not exists judge_reasoning_audits (
    id                  uuid primary key default gen_random_uuid(),
    run_at              timestamptz not null default now(),
    decision_id         uuid not null references judge_decisions(id) on delete cascade,
    audit_model         text not null,
    supported           boolean not null,
    unsupported_claims  jsonb not null default '[]',
    notes               text,
    -- Per the CostGuard-extension convention (PHASE3_LOCKED_DECISIONS.md):
    -- registered in COST_TRACKED_TABLES (app/llm/cost.py).
    estimated_cost      numeric,
    created_at          timestamptz not null default now()
);

create index if not exists idx_judge_reasoning_audits_decision_id
    on judge_reasoning_audits (decision_id);
