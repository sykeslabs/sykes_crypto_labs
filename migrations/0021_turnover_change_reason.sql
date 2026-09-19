-- Real bug fix (2026-09-17): `portfolio_allocation_changes` carried no
-- record of WHY a target changed, so `get_turnover_since` (the query
-- MAX_WEEKLY_TURNOVER is checked against) summed every persisted target
-- delta uniformly -- including the A1 WATCH/NO_TRADE risk-control
-- correction (`min(current_allocation, MAX_SINGLE_ASSET_ALLOCATION)`,
-- app/risk/engine.py's `size_one`), which `RiskEngine._strategy_turnover_
-- delta` deliberately treats as ZERO strategy turnover at decision time
-- (these are explicitly "not sizing decisions," per PHASE3E_PROMPT.md's
-- own framing -- see that method's docstring). The exemption existed only
-- in memory (on `SizedDecision`) and was lost the moment the row was
-- persisted, so every future run's budget calculation silently re-counted
-- it as real strategy turnover. Live-confirmed: 5 of the 8 real historical
-- `portfolio_allocation_changes` rows (58.7% of all turnover-relevant
-- delta ever recorded under the current baseline) are risk-control
-- corrections, not strategy decisions -- see doc/history.md's Phase 5k
-- section for the full incident and the live re-derivation.
--
-- `change_reason` is the AUTHORITATIVE classification going forward,
-- persisted from the already-gated `SizedDecision.decision` at
-- portfolio-construction time (app/portfolio/construction.py) -- never
-- reconstructed later from `judge_decisions.decision` (the RAW, pre-gate
-- value), confidence, or any other derived signal. A raw BUY/SELL that
-- the confidence gate downgrades to WATCH/HOLD before sizing must be
-- classified by what it BECAME, not what it started as -- see the real
-- 2026-09-17 NEAR row below, whose raw judge_decisions.decision is "BUY"
-- (confidence 0.50, below the 0.55 min_buy_confidence gate) but whose
-- actual, gated, effective decision was WATCH.
--
-- Idempotent -- safe to re-run: the column-add is a no-op if it already
-- exists, and the backfill UPDATE below is scoped to this migration's own
-- exact, named historical rows (by id), never to a heuristic condition
-- that could accidentally re-match a future row.

alter table portfolio_allocation_changes
    add column if not exists change_reason text not null default 'strategy';

-- One-time backfill of the 8 rows that existed before this migration,
-- independently re-verified live against real judge_decisions.decision/
-- confidence and the real confidence-gate thresholds
-- (MIN_BUY_CONFIDENCE=0.55, MIN_SELL_CONFIDENCE=0.50,
-- MIN_REBALANCE_CONFIDENCE=0.50 -- confirmed via .env and git history to
-- have been constant throughout this project's life, never overridden
-- differently at any point) before writing this list. Every row not
-- named here keeps the column's own 'strategy' default, which is already
-- correct for them (re-verified, not assumed).
--
-- risk_control (the A1 WATCH/NO_TRADE correction, confirmed by decision
-- type alone for 4 of these 5, and by re-deriving the confidence gate for
-- the 5th -- NEAR 2026-09-17, raw BUY at confidence 0.50):
update portfolio_allocation_changes
set change_reason = 'risk_control'
where id in (
    '98400b19-09df-4585-af21-d7989a3c3e28',  -- BTC  2026-09-15 WATCH
    'dfa20cc1-d044-4221-9ea7-eafd50539d66',  -- BNB  2026-09-16 WATCH
    '66f5640b-4bda-4963-bb85-efac41038618',  -- HYPE 2026-09-16 WATCH
    'ec5d2a63-cba0-4f88-9cad-118bf450bf6a',  -- NEAR 2026-09-17 BUY@0.50 -- gated to WATCH
    'ffee7164-c3a7-4e39-9d4b-28ff5963e65e'   -- JASMY 2026-09-17 NO_TRADE
);
