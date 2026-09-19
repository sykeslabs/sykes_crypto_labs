## Development methodology

This project is built and verified one phase at a time (see Status above) — each
phase is implemented, tested against a live Supabase project, and reviewed before
the next begins. Live trading is only ever activated after a separate, explicit
safety review; the default and current mode is PAPER.

Starting with Phase 3, this also applies *within* a phase: Phase 3 is large
enough that it is split into sub-phases (3a–3i, plus the optional, gated 3j
and 3k addenda — see their own gating rules below), each with its own live
verification and cost check, rather than implemented as one block. Rules that
carry across every sub-phase:

- **Official, documented sources come before fragile/unofficial ones.**
  Coinbase, Binance, Deribit, Etherscan, and DefiLlama all have real,
  documented, free-or-cheap APIs and are built in 3b/3c. CryptoBubbles,
  CoinAnk, and PlanB/X have unclear or unofficial access and are deliberately
  built last (3f), gated on a real feasibility check each time.
- **No new external source is assumed reliable until checked.** Programmatic
  access is verified for real before code is written against it; sources that
  turn out to be unavailable are recorded as such (`signal_sources` table),
  not faked or silently dropped.
- **No new evidence source ships without a cost estimate** against
  `MAX_DAILY_LLM_COST` / `MAX_MONTHLY_LLM_COST`. Any sub-phase that adds LLM
  calls (3d, 3f) estimates calls/day and cost/day before merging. Market-data
  sources (3b, 3c) have no LLM cost but should still be checked against
  provider rate limits. A small number of 3c/3f/3i sources (on-chain
  valuation metrics, token unlock schedules, social/narrative sentiment,
  entity-flow intelligence, developer-activity aggregation) may require a
  paid data-API subscription — a dollar cost against project budget, tracked
  and documented separately from `CostGuard`, which exists specifically to
  cap LLM spend, not general data-vendor spend.
- **Two schema/convention decisions were locked before 3a started**, since
  schema is cheap to decide up front and expensive to retrofit once 3b–3g
  are writing against it (see `prompts/PHASE3_LOCKED_DECISIONS.md` for the full
  writeup):
  - The full Judge decision record (thesis, key/contradictory evidence,
    invalidation conditions) lives in a dedicated `judge_decisions` table,
    reserved empty in 3a and populated in 3e — not folded into the slimmer
    `decision_outcomes` ledger, which only tracks resolution against
    realized returns. `decision_outcomes.decision_id` FKs to it.
  - Every table that persists an LLM call's result must have an
    `estimated_cost` column and be registered in a documented
    `COST_TRACKED_TABLES` list in `app/llm/cost.py` that CostGuard sums
    across — so a later sub-phase adding a new LLM-call table
    (`model_market_assessments` in 3d, `judge_decisions` in 3e, bull/bear/
    scenario tables in 3f, reasoning-audit calls in 3g) can't silently
    under-report real spend against `MAX_DAILY_LLM_COST`/
    `MAX_MONTHLY_LLM_COST` by forgetting to wire it in.
- **Predictions are tracked against reality, continuously.** Starting in 3e,
  every Judge decision is recorded in a decision-outcome ledger and later
  backfilled with realized returns, so the system's own accuracy — not just
  its internal model agreement — is measurable and improves the design over
  time rather than being assessed once at the end.
- **An accuracy claim isn't accepted until it survives multiple-testing and
  calibration checks, not just a hit-rate.** Every prompt or logic change
  followed by a calibration re-run is a "trial" in the statistical sense —
  enough trials against the same historical data will eventually produce a
  good-looking number by chance. From 3e onward this project tracks that
  trial count (`calibration_runs`, `prompt_templates`) and, in 3g, applies
  Deflated Sharpe / probability-of-backtest-overfitting correction before
  treating any before/after comparison as a real improvement. Directional
  hit-rate alone is also insufficient — confidence values feed position
  sizing directly, so calibration (Brier score / reliability by regime)
  is tracked as a separate, equally-required metric, and a held-out decision
  window is reserved from 3e onward specifically so at least one result
  hasn't been iterated against.
- **New tooling earns its place by matching a real need, not by being
  available.** FastAPI, xAI, LangChain/LangGraph, and Langfuse are each
  adopted for a specific, scoped reason (see "Technology stack decisions"
  above) and introduced only in the phase where that reason applies —
  MongoDB was considered and deliberately not adopted, for the same kind of
  reasoning; order-flow imbalance/LOB microstructure features were
  considered and deliberately not adopted for the same reason, on a
  horizon-mismatch basis rather than an availability basis (see "Technology
  stack decisions"). **3j and 3k apply this rule to evidence sources, not
  just infrastructure**: options gamma exposure, exchange counterparty/
  solvency risk, and retail-demand proxies (3j), and DeFi lending rates,
  staking yield/validator queue depth, and stablecoin depeg-risk monitoring
  (3k), were all identified as things professional crypto desks track, but
  none is scheduled for implementation until 3h's evidence-value ranking
  (or 3g's Judge-reasoning audit or purged-walk-forward finding) shows a
  specific, named gap one of them would close — being used elsewhere is
  not, by itself, a reason to add a new cost-bearing, drift-prone input to
  this system.
- **A learned model is a checking tool until proven otherwise, never a
  silent decision-maker.** 3h's evidence-value ranking exists specifically
  to catch cases where the Judge's narrative weighting and a
  statistically-learned weighting disagree — but a small-sample learned
  model is exactly as vulnerable to the multiple-comparisons/overfitting
  problem 3g exists to correct for, so it stays diagnostic-only (reported
  alongside `composite_factor_score`, never blended into the Judge or used
  to auto-adjust `signal_sources`) until it has survived the same kind of
  scrutiny 3g applies to the Judge itself.
- **Point-in-time integrity is checked, not assumed.** Several evidence
  types (on-chain valuation metrics, ETF flow figures, regulatory-event
  extraction) get revised by their own provider after the fact. From 3a
  onward, revisable fields are append-only (`is_revision_of`, never an
  overwrite) so a "value as known at time T" query is always available, and
  3g explicitly audits a sample of resolved decisions to confirm no
  since-revised value leaked into a historical evaluation. An accuracy
  number that turns out to be quietly using hindsight is worse than an
  honestly-reported low accuracy number, because it fails silently.
- **Model/source disagreement is a risk-sizing input, checked for whether it
  actually earns that role.** 3d/3e compute `model_agreement`/
  `source_agreement` as evidence distinct from any single model's
  confidence, and 3e's Risk Engine scales position size down when
  agreement is weak, composed with (not instead of) volatility-based
  sizing. 3g then checks — via a reliability breakdown by agreement bucket,
  the same discipline already applied by regime — whether low-agreement
  decisions genuinely resolve less reliably than high-agreement ones at the
  same stated confidence, rather than assuming disagreement is informative
  just because it's intuitive that it should be.
- **Execution realism is part of the accuracy claim, not a separate
  concern.** Every calibration/stress-test number produced through 3g/3h is
  computed against mark-to-mid `market_snapshots` prices, which assumes
  costless, instant fills. Phase 4 does not treat this as good enough to
  call "paper trading" — it adds order-book-depth-aware, fee-aware fill
  simulation and re-reports calibration net of realistic execution costs,
  specifically because a system's real-world accuracy is only as
  trustworthy as the fill assumptions behind the numbers describing it.
- **Documentation is a living part of the project, not an afterthought
  (standing policy adopted 2026-09-16).** Every substantial task — code or
  not — follows Understand → Implement → Test/Validate → Update
  Documentation → Update Context → Verify Consistency → Complete. `doc/`
  files are treated as operational instructions for the next agent, not
  passive notes: code is implementation truth, `architecture.md` is
  architecture truth, this file is process truth, `decisions.md` is
  historical-rationale truth, `history.md` is historical-fact truth, and
  each fact lives in exactly one of these, cross-linked rather than
  duplicated. A decision recorded after the fact must distinguish observed
  fact from inferred rationale, never fabricating reasoning that wasn't
  actually the reason at the time. Before calling any substantial task
  complete, ask: if another agent started working on this repository
  tomorrow, would the documentation and context files correctly describe
  the system after this change? If not, it isn't done yet.
