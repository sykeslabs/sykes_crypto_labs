-- Phase 5b addendum: real "effective" (realized) alpha, alongside the
-- Judge's own predicted `expected_alpha` (judge_decisions) -- stored
-- ALONGSIDE the existing mark-to-mid `realized_return`/
-- `realized_return_net_of_costs`, never instead of them.
-- `benchmark_return` = BTC's own realized_return over the exact same
-- [decision_timestamp, evaluated_at] window (a straight two-point
-- buy-and-hold return, not a triple-barrier-resolved one -- BTC has no
-- target/stop of its own here, it's a passive benchmark).
-- `effective_alpha` = realized_return - benchmark_return.
-- Idempotent -- safe to re-run.

alter table decision_outcomes
    add column if not exists benchmark_return numeric;

alter table decision_outcomes
    add column if not exists effective_alpha numeric;
