-- Phase 3f: adversarial bull/bear research + scenario modeling. A new
-- table — macro observations, the forward-looking macro-event calendar,
-- and the regional exchange premium all reuse 3a's existing
-- `evidence_observations` shape (MACRO/ASSET scope), no new tables needed
-- for those. Idempotent — safe to re-run.

create table if not exists adversarial_research (
    id                uuid primary key default gen_random_uuid(),
    run_id            text not null,
    asset_id          uuid not null references assets(id) on delete cascade,
    prompt_template_id uuid references prompt_templates(id),
    bull_case         jsonb not null default '{}',
    bear_case         jsonb not null default '{}',
    -- Nullable: only populated when the second bull-rebuts-bear pass is run.
    bull_rebuttal     jsonb,
    scenarios         jsonb not null default '{}',
    -- Per the CostGuard-extension convention (PHASE3_LOCKED_DECISIONS.md):
    -- registered in COST_TRACKED_TABLES (app/llm/cost.py). One row's cost is
    -- the sum of all LLM calls (bull + bear + rebuttal + scenario) that
    -- produced it.
    estimated_cost    numeric,
    created_at        timestamptz not null default now()
);

create index if not exists idx_adversarial_research_run_id
    on adversarial_research (run_id);

create index if not exists idx_adversarial_research_asset_created
    on adversarial_research (asset_id, created_at desc);
