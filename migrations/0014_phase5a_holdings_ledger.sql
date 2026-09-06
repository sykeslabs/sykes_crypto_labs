-- Phase 5a: ground-truth current holdings, entered by hand -- the ONLY
-- input this project accepts for "what do I actually own right now."
-- Append-only (never an in-place overwrite): editing or removing a
-- holding is a NEW row, never a mutation of a prior one, so "what did I
-- hold as of date T" stays answerable later, same convention 3a already
-- established for revisable evidence.
--
-- asset_id NULL is a reserved, distinct value meaning "the cash line" --
-- quantity is then a stated USD amount directly, not asset units. This is
-- the only way to represent uninvested cash (Portfolio Construction never
-- forces full capital deployment, so a real holdings state is very often
-- partially cash).
--
-- This table is the SOLE input to current_allocation going forward (see
-- README's Phase 5a section) -- portfolio_positions is retired as an
-- input; it continues to be written by Portfolio Construction as its own
-- derived output bookkeeping only. Idempotent -- safe to re-run.

create table if not exists holdings_ledger (
    id              uuid primary key default gen_random_uuid(),
    asset_id        uuid references assets(id) on delete restrict,
    quantity        numeric not null check (quantity >= 0),
    cost_basis_usd  numeric,
    recorded_at     timestamptz not null default now(),
    created_at      timestamptz not null default now()
);

create index if not exists idx_holdings_ledger_asset_recorded
    on holdings_ledger (asset_id, recorded_at desc);
