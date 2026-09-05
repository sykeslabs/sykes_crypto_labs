# AI Crypto Portfolio — Phase 3i: Entity-Flow Intelligence, Custody/OTC Flow, Network & Developer Fundamentals

## Context

This is a second later addendum to Phase 3, identified from the same
gap-analysis pass against professional crypto-advisory/quant research
practice that produced 3h. Unlike 3h, this sub-phase is **not**
diagnostic-only — it adds three new, genuinely distinct evidence sources
to the pipeline, the same kind of work as 3b/3c, just discovered later.
It is now the **last** sub-phase of Phase 3 — Phase 4 (paper trading
execution, benchmarks, ongoing accuracy tracking) follows this one.

**Before writing any code**, inspect what actually exists: the
`ENTITY_FLOW_INTELLIGENCE`, `CUSTODY_OTC_FLOW`, and
`NETWORK_FUNDAMENTALS_DEV_ACTIVITY` rows seeded as `NOT_IMPLEMENTED` in 3a's
`signal_sources`, the real Etherscan/on-chain provider shape from 3c
(especially its documented large-transfer-count limitation — no entity
clustering), the real Judge input shape from 3e/3f, and 3h's evidence-value
reporting (so this sub-phase's new sources become inputs 3h's *next* run,
whenever that happens, can actually rank). This sub-phase adds evidence
inputs; it does not touch the Judge's decision logic, the Risk Engine's
formulas, or Portfolio Construction — it extends the input set the same way
3f did.

## Non-negotiables

- PAPER ONLY.
- Official/documented paid-tier APIs only — no invented access, no
  undocumented scraping presented as a supported integration. If reliable
  access to a given provider doesn't exist at a usable tier, the source
  stays `UNAVAILABLE`/`NOT_IMPLEMENTED` in `signal_sources`, same rule as
  every prior sub-phase.
- Zero new LLM calls. This sub-phase is pure data collection plus wiring new
  labeled inputs into the Judge's existing single structured call (3e) —
  extending what's in the prompt context is not a new LLM call.
- A paid data-API subscription (entity-flow intelligence and, potentially,
  a developer-activity aggregator) is a dollar cost to document in the
  README's cost section, same as 3c's on-chain valuation-metrics providers
  — it does not run through `CostGuard`, which exists specifically to cap
  LLM spend, but it's still a deliberate, documented decision, not an
  unexamined recurring charge.
- Follow the 3a evidence-provenance shape (including `decay_half_life_hours`)
  for every new table. These are meaningfully different decay rates: entity
  flow and custody/OTC balances change with each on-chain transaction
  (hours-scale), while developer activity is inherently slow-moving
  (weeks-scale) — don't default all three to the same half-life.
- Never auto-convert any of these three sources into a directional signal
  at the collector level — same rule as every prior evidence source. Store
  raw observations; interpretation is the Judge's job (3e/3f).
- The held-out decision window and its tagging convention
  (`regime_at_decision`, `judge_confidence`, `in_holdout_window`) established
  in 3e continues unchanged — new decisions made during 3f/3g/3h/3i tag the
  same way; this sub-phase does not get its own separate bookkeeping and
  does not retroactively reclassify any existing `decision_outcomes` row.

## Task detail

**1. Feasibility check — before writing any provider code:**
- **Entity-flow intelligence**: check Nansen and Arkham Intelligence's
  actual documented API access, what wallet-entity labels and "smart
  money"/fund cohort flow data are genuinely available at a usable tier,
  real rate limits, and real pricing. If neither offers reliable
  programmatic access at a reasonable cost, `status = UNAVAILABLE` — this
  closes a documented limitation from 3c (the raw large-transfer-count
  proxy's inability to distinguish genuine whale activity from routine
  exchange-internal traffic), but that limitation staying open is an
  acceptable outcome, not a failure, same standard as every fragile source
  in 3f.
- **Custody/OTC desk flow**: determine what's genuinely derivable — e.g.
  publicly-known custody-provider wallet addresses (Coinbase Custody,
  Fidelity Digital Assets, and similar) tracked via the same on-chain
  explorer already integrated in 3c, or a documented aggregator if one
  exists with real coverage. This is likely to be a narrower proxy (known
  address balance deltas) rather than a full custody-flow product — that's
  fine, ship the narrower version and mark the fuller version
  `NOT_IMPLEMENTED`, same rule as 3c's exchange-reserve proxy.
- **Network usage fundamentals**: confirm active-address counts,
  transaction throughput, and fee-revenue data are genuinely accessible per
  asset from the on-chain explorer(s) already integrated (3c) — this is
  likely near-zero marginal cost since it's the same data source, just
  different fields.
- **Developer activity**: check real access to a documented aggregator
  (e.g. Electric Capital's Developer Report data, if programmatically
  accessible) versus a narrower direct-GitHub-API approach (commit/
  contributor counts against a project's known repos, where a project's
  primary repo is unambiguous — mark ambiguous or multi-repo/forked
  projects `UNAVAILABLE` rather than guessing which repo is authoritative).

For each: if reliable access exists, build a provider following the 3a
evidence-provenance shape. If not, implement the provider abstraction
returning `status = UNAVAILABLE` and stop there for that source. Update
`signal_sources` accordingly either way.

**2. Entity-flow intelligence (`ENTITY_FLOW_INTELLIGENCE`).**
Where access exists, capture net flow direction and magnitude for labeled
entity cohorts (e.g. known funds, market makers, "smart money" wallets vs.
retail-labeled clusters) per asset. **Interpretation constraint:** entity
labels are the provider's own inference and carry their own error rate —
store the label/cohort as reported, and note in `signal_sources.notes`
that label accuracy is provider-dependent and unverified by this project
directly. A labeled "smart money" cohort accumulating is a distinct,
higher-confidence fact than an unclustered large transfer (3c), but it is
still not a directional signal on its own — crowded "smart money" longs can
be as wrong as crowded retail longs. This is additive to, not a replacement
for, 3c's existing large-transfer-count proxy, which stays in place for
assets/chains without entity-flow coverage.

**3. Custody/OTC desk flow (`CUSTODY_OTC_FLOW`).**
Where access exists, capture balance deltas for known custody/OTC-desk
addresses per asset, distinct from both the exchange-reserve proxy (3c,
public exchange balances) and spot ETF flows (3c, fund-level capital
movement) — this specifically targets the growing share of institutional
activity that never touches a public exchange order book or a fund
wrapper. **Interpretation constraint:** a balance increase at a known
custody address has multiple benign explanations (a new institutional
client onboarding, an existing client moving assets between custody
providers, collateral posting) beyond net new buying — store the raw
balance delta; do not infer "institutional accumulation" at the collector
level.

**4. Network usage fundamentals (`NETWORK_FUNDAMENTALS_DEV_ACTIVITY`,
part 1).**
Capture active-address count, transaction throughput, and fee revenue per
asset/chain, trended over 7d/30d, where the on-chain explorer already
integrated in 3c has coverage. **Interpretation constraint:** rising usage
is not automatically bullish — it can reflect genuine adoption, but also
bot/spam activity inflating address counts, or rising fees pricing out
casual users even as revenue climbs. Store the raw metrics and their trend;
the Judge weighs plausible explanations, same as every other source here.

**5. Developer activity (`NETWORK_FUNDAMENTALS_DEV_ACTIVITY`, part 2).**
Capture commit velocity and/or active-contributor count per asset where a
project's primary repository is unambiguous, trended over a consistent
window (e.g. 30d/90d). **Interpretation constraint:** this is a slow-moving
fundamentals signal on a multi-month-to-multi-year horizon, not a timing
signal — a short-term dip doesn't imply abandonment (mature, stable
codebases legitimately commit less often than early-stage ones), and a
commit spike doesn't imply an imminent catalyst. Store raw counts and
trend; avoid presenting either as inherently bullish/bearish.

**6. Update `signal_sources`.**
Reflect real, verified status for `ENTITY_FLOW_INTELLIGENCE`,
`CUSTODY_OTC_FLOW`, and `NETWORK_FUNDAMENTALS_DEV_ACTIVITY` individually —
they may end up with different reliability/coverage even though two of them
piggyback on the same underlying on-chain explorer relationship.

**7. Wire into the existing Judge from 3e/3f.**
Add each newly-available source as a distinct, labeled
`source_assessment`-style input to the Judge's context, following the same
"extend the input set, don't redesign the Judge" pattern 3f already used
for bull/bear/macro evidence. `UNAVAILABLE` sources must appear as such in
the Judge's context, not be silently omitted, same rule as every prior
sub-phase.

**8. Cost sizing.**
Document any paid-tier dollar cost (entity-flow intelligence provider,
developer-activity aggregator if a paid one is used) in the README's cost
section, separate from `CostGuard`/`MAX_DAILY_LLM_COST`, same treatment as
3c's on-chain valuation-metrics providers.

**9. Re-run calibration, honestly counted.**
Since this sub-phase changes the Judge's evidence inputs, re-run the
calibration script (hit-rate + Brier score, by regime) and persist the
result to `calibration_runs` like every prior calibration attempt — this
is itself a new trial in the sense 3g's Deflated Sharpe/PBO correction
cares about. Do not present any before/after delta from this run as a
confirmed accuracy improvement on its own; 3g's methodology, not a single
raw comparison, is what adjudicates that. If a meaningful amount of
`decision_outcomes` history accumulates after this sub-phase, a follow-up
re-application of 3g's statistical validation (and 3h's evidence-value
ranking, now with these three new fields available to it) against the
larger sample is a reasonable next step — but that's future work, not part
of this sub-phase's exit criteria.

**10. Tests & docs.**
`pytest` passes without live credentials (mocked responses per new
provider, including an `UNAVAILABLE` case for any source that doesn't clear
the feasibility check). Update `README.md`: mark 3i complete, document real
availability/cost findings per source, and note the calibration re-run
result with the same "provisional, not a confirmed improvement" framing
3f used.

## Exit criteria

- `signal_sources` reflects real, verified status for
  `ENTITY_FLOW_INTELLIGENCE`, `CUSTODY_OTC_FLOW`, and
  `NETWORK_FUNDAMENTALS_DEV_ACTIVITY`.
- Each source that clears its feasibility check produces live, provenance-
  shaped observations for assets with genuine coverage, `UNAVAILABLE`
  elsewhere — not forced universe-wide.
- The Judge's context includes each newly-available source as a distinct,
  labeled input, visible in `source_assessment`, not blended into
  `confidence`.
- Any source that fails its feasibility check is documented as
  `UNAVAILABLE`/`NOT_IMPLEMENTED` with the real reason (access, coverage, or
  cost), not silently dropped.
- Calibration re-run persisted to `calibration_runs`, reported with the
  same provisional framing as 3f's before/after comparison.
- Zero new LLM calls/cost. Any paid data-API subscription is a documented
  dollar cost, separate from and not routed through `CostGuard`.
- `pytest` green without credentials.
- README updated with real findings, not placeholders.

This completes the **required** scope of Phase 3. A third gap-analysis
addendum, **3j** (options gamma/dealer-positioning, exchange counterparty/
solvency risk, and retail-demand proxies), exists as a documented but
explicitly optional backlog item — see `PHASE3J_PROMPT.md` for why it's
gated on 3h's evidence-value ranking rather than scheduled by default.
Report what was actually achievable per source (entity-flow intelligence,
custody/OTC flow, network usage fundamentals, and developer activity), the
calibration re-run result, and wait for confirmation before starting either
3j (only if 3h's findings justify it) or Phase 4 directly (paper trading
execution, benchmarks, and ongoing accuracy tracking against the now
fully-validated, stress-tested, and evidence-complete baseline).
