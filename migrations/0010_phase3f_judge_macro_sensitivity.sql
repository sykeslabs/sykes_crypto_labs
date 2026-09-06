-- Phase 3f task 5: "Require an explicit macro_sensitivity reasoning output
-- per candidate asset — how does this macro development affect this
-- specific asset — rather than a blanket assumption applied uniformly."
-- A new column, not an edit to any prior migration. Idempotent.

alter table judge_decisions
    add column if not exists macro_sensitivity text;
