-- Phase 5b: extends holdings_ledger from a snapshot-per-asset model
-- (latest row wins) to a genuinely transactional one -- multiple BUY/SELL
-- rows per asset now sum into the current position (see
-- app/portfolio/holdings.py's aggregate_current_holdings), rather than
-- the latest row silently replacing every prior one.
--
-- purchased_at is the real date the asset was bought/sold at that price --
-- distinct from recorded_at (when the row was entered into the ledger).
-- Nullable: existing rows predate this column and must not have a
-- fabricated value backfilled into them.
--
-- transaction_type distinguishes a BUY (adds to the running position) from
-- a SELL (subtracts) -- explicit and auditable rather than an implicit
-- sign convention on quantity, which stays non-negative either way.
-- Defaults to 'BUY' for existing rows, which is accurate: every row
-- entered before this migration was a real buy. The cash line's own
-- semantic is unchanged by any of this -- it stays a single absolute
-- stated USD amount (the latest cash row), never summed with prior ones.
--
-- Idempotent -- safe to re-run.

alter table holdings_ledger
    add column if not exists purchased_at timestamptz,
    add column if not exists transaction_type text not null default 'BUY'
        check (transaction_type in ('BUY', 'SELL'));
