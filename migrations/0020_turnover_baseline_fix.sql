-- Real bug fix (2026-09-14): portfolio_allocation_changes.previous_allocation
-- used to mean "real, ground-truth holdings at decision time" -- so a manual
-- /holdings trade that moved real holdings away from the system's own last
-- target got counted as STRATEGY turnover the next time the Judge revisited
-- that asset (see app/risk/engine.py's RiskEngine._strategy_turnover_delta
-- docstring for the full real incident and backtest evidence: total raw
-- turnover across the same 14 real live runs was 318.30% measured the old
-- way vs. 89.23% measured against the system's own previous target).
--
-- Going forward, previous_allocation/new_allocation mean the system's own
-- target (portfolio_positions.current_allocation) before/after each event.
-- actual_allocation_before is the real holdings-based allocation at the
-- same moment, kept for audit visibility only -- never summed into
-- turnover. baseline_semantics disambiguates old rows (written under the
-- real-holdings meaning) from new ones, WITHOUT rewriting or deleting any
-- historical number -- those rows are genuine historical fact under their
-- own real semantics and stay exactly as recorded.
--
-- Idempotent -- safe to re-run.

alter table portfolio_allocation_changes
    add column if not exists actual_allocation_before numeric;

alter table portfolio_allocation_changes
    add column if not exists baseline_semantics text not null default 'system_target';

-- One-time backfill: every row that already exists was written under the
-- OLD (real-holdings) semantics -- annotate them as such.
--
-- Genuinely safe to re-run at ANY time (a real correctness fix over an
-- earlier draft of this migration, found in a 2026-09-14 pre-production
-- audit): the WHERE clause also requires actual_allocation_before IS NULL.
-- A row written by the FIXED code always populates a real, non-null
-- actual_allocation_before (app/portfolio/construction.py always sets it
-- from the real current_allocation, never omitted) -- so this can never
-- match a genuine new 'system_target' row, no matter how many real rows
-- have been written since this migration first ran. Matching on
-- `baseline_semantics = 'system_target'` alone (this migration's own
-- column-default value) would NOT have this guarantee -- a second run
-- after real new rows existed would have silently mislabeled them as
-- 'actual_holdings', excluding real future turnover from accounting.
update portfolio_allocation_changes
set baseline_semantics = 'actual_holdings'
where baseline_semantics = 'system_target'
  and actual_allocation_before is null;
