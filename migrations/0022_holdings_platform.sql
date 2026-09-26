-- Phase 5o (real holdings import, 2026-09-26): holdings_ledger gains a
-- required custody-location dimension. Every existing row in this table
-- is the mockup portfolio (BTC 0.01, SOL 5.0, ADA 130, JASMY 20, CASH
-- $1000) and is deleted as part of this same migration/import -- see
-- scripts/import_real_holdings.py -- so there is no "what do I honestly
-- backfill onto old rows" problem the way transaction_type/purchased_at
-- had in migrations 0014/0015: every row that exists after this runs will
-- have been freshly inserted with a real, known platform. `not null`, no
-- default, deliberately -- a future manual entry with no stated platform
-- should fail loudly, not silently default to one location.
--
-- source_type is purely descriptive (the real original Coinbase
-- transaction type, e.g. 'Staking Income', 'Advanced Trade Buy',
-- 'Convert', 'Internal Transfer', or NULL for a manual dashboard entry) --
-- never read by aggregate_current_holdings()'s cost-basis math, which
-- only looks at transaction_type/quantity/cost_basis_usd. Kept for a
-- future staking/reward-income view, not built in this migration.
--
-- Idempotent -- safe to re-run.

alter table holdings_ledger
    add column if not exists platform text
        check (platform in ('coinbase', 'ledger_wallet')),
    add column if not exists source_type text;

-- Removes the mockup portfolio (BTC 0.01, SOL 5.0, ADA 130, JASMY 20,
-- CASH $1000) -- real, deliberate, and required here (not left to the
-- import script) so the NOT NULL constraint below can actually be applied
-- in this same migration, rather than leaving `platform` nullable
-- indefinitely. scripts/import_real_holdings.py inserts the real
-- replacement data afterward.
delete from holdings_ledger;

alter table holdings_ledger
    alter column platform set not null;
