-- Phase 4 task 2: fee/slippage-adjusted realized return, stored ALONGSIDE
-- (never instead of) the existing mark-to-mid `realized_return` — so "how
-- much did execution realism cost us" is itself a reportable number.
-- Idempotent — safe to re-run.

alter table decision_outcomes
    add column if not exists realized_return_net_of_costs numeric;

alter table decision_outcomes
    add column if not exists assumed_fill_method text;
