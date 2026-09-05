# AI Crypto Portfolio — Phase 3k: Deferred Evidence Backlog II (Gated, Optional)

## Context

This is a **fourth** gap-analysis addendum, following the same pattern as
3h (adaptive evidence-value weighting, stress testing), 3i (entity-flow,
custody/OTC, network fundamentals), and 3j (options gamma exposure, exchange
counterparty/solvency risk, retail-demand proxies) — all added after
comparing this project against professional crypto-advisory practice. This
pass surfaced three more candidate signal sources, distinct in kind from
everything in 3j:

1. **DeFi lending/borrowing rates** (e.g. Aave/Compound supply and borrow
   APYs, pool utilization) as a leverage/carry proxy — distinct from 3c's
   DeFi TVL flows (which measure capital location) and from funding rates
   (which measure perpetual-futures leverage specifically). Rising borrow
   demand/utilization against stable collateral is a different leverage
   signal than either.
2. **Staking yield / validator queue depth** for proof-of-stake assets
   (e.g. ETH) — activation/exit queue length and real staking yield speak to
   supply-side lockup dynamics that 3c's MVRV/SOPR/NUPL cohort metrics don't
   capture, since those are valuation-cycle metrics, not staking-specific
   supply mechanics.
3. **Stablecoin depeg-risk monitoring** — distinct from 3c's stablecoin
   supply/velocity (a capital-rotation proxy): this is a narrower, tail-risk
   flag tracking a specific stablecoin's price deviation from its peg across
   venues, in the same monitoring spirit as 3j's exchange counterparty-risk
   flag rather than a directional evidence input.

**A fourth candidate was explicitly considered and rejected, not just
omitted:** order-flow imbalance / limit-order-book microstructure features.
This project's "Technology stack decisions" section already documents a
deliberate "considered, not adopted" call on exactly this category — LOB
features have real short-horizon predictive value on official venues, but
that value is validated for sub-minute-to-intraday statistical/ML models
with their own leakage-control methodology, not for this project's Judge,
which reasons on multi-day-to-multi-month horizons via structured LLM
evidence. That reasoning still holds and is not reopened by this addendum;
if a shorter-horizon component is ever wanted, the README already says it
should be its own scoped phase with its own validation approach, not folded
in here.

**Like 3j, 3k is not scheduled by default.** This project's stated
methodology is explicit: *"new tooling earns its place by matching a real
need, not by being available"* (README, Development methodology). At the
time this addendum was written, there is no evidence that the 3a–3j evidence
set is under-performing in a way these three sources would fix — they were
identified by comparing against what professional desks track, not by any
finding that this system's accuracy or calibration is currently limited by
their absence. Shipping them speculatively would repeat exactly the
feature-creep risk 3j's own gate was written to prevent, and doing so twice
over (once for 3j's sources, once for these) would not make it more
justified the second time.

## Gate — read before doing anything else

**Do not start implementation work on 3k until both of the following are
true, and document that they're true before writing code:**

1. **3h's evidence-value ranking has run** (full-history and rolling/
   regime-sliced) against a real `decision_outcomes` history large enough to
   clear its own minimum-sample-size threshold — not "insufficient data."
   If 3j has already been evaluated (gate met or not), that same ranking run
   can be reused here; this does not require a second, separate ranking run
   solely for 3k unless meaningful new decision history has accumulated
   since 3j's gate check.
2. **That ranking, or 3g's Judge-reasoning audit, or 3g's purged/embargoed
   walk-forward finding, shows a specific, named gap** one of these three
   sources would plausibly close — e.g. "the Judge is repeatedly wrong-
   footed by ETH-specific moves around validator-queue backlogs and no
   current source explains why" (→ motivates staking yield/queue depth), or
   "a specific historical drawdown in the 3h stress-test scenarios coincided
   with a stablecoin trading materially off-peg and the system had no
   leading indicator for it" (→ motivates depeg monitoring), or "DeFi-heavy
   candidates are mispriced during periods of elevated on-chain leverage
   that TVL/funding data alone doesn't surface" (→ motivates
   lending-rate/utilization tracking).

If neither condition holds, the correct action is to **not implement 3k**,
full stop — not to implement "the easy one anyway." Revisit this gate
periodically as more `decision_outcomes` history accumulates in Phase 4,
rather than treating "not now" as "never." If both 3j and 3k are pending at
the same gate-check point, evaluate them together against the same ranking
run and implement only whichever specific sources (from either list) clear
the bar — there is no requirement to resolve 3j before considering 3k or
vice versa.

If the gate is met for only one of the three sources, implement only that
one — 3k is not an all-or-nothing sub-phase like 3b/3c were.

## Non-negotiables (apply to whichever source(s) clear the gate)

- PAPER ONLY.
- Same feasibility-check discipline as 3f/3j: verify real, documented
  programmatic access before writing any collector code. Record
  `UNAVAILABLE`/`NOT_IMPLEMENTED` in `signal_sources` for anything that
  doesn't check out, same as every prior sub-phase.
- Each source ships with the same cost-sizing discipline as every other
  sub-phase: a documented dollar cost (if any paid tier is required) against
  project budget, and zero new LLM cost unless explicitly justified and
  `CostGuard`-gated.
- Each source is wired into the Judge as a distinct, labeled
  `source_assessment` entry — never blended into `confidence` or any other
  source's value — except stablecoin depeg-risk monitoring, which (like
  3j's exchange counterparty risk) is a monitoring/flagging signal surfaced
  alongside 3h's stress-test output rather than a directional Judge input.
- Because this sub-phase is gated on a specific named finding (see above),
  each source's README write-up must explicitly reference which 3g/3h
  finding motivated it — not just "this is a source professional desks use."
- After implementation, re-run 3g-style calibration and 3h-style
  evidence-value ranking specifically for the new source, with the same
  "provisional, not a confirmed improvement" framing 3f/3i/3j used — closing
  the loop on whether the named gap was actually closed, not just assuming
  it was because the source is now present.

## Task detail (implement only sources that cleared the gate)

**1. DeFi lending/borrowing rates.**
Aave/Compound (or equivalent major protocols already reachable via 3c's
DefiLlama integration, which publishes pool-level rate data alongside TVL)
supply/borrow APYs and utilization ratios for major collateral assets.
Verify real, documented access (DefiLlama's yields/pools endpoints, or the
protocols' own subgraphs) before committing to an implementation approach.
Store as a new evidence type, `DEFI_LENDING_RATES`, registered in
`signal_sources`. Interpretation constraint: rising utilization/borrow rates
are not automatically bearish (could reflect either speculative leverage
buildup or healthy demand) — store the raw rates/utilization; the Judge
reasons about them alongside 3c's funding rates and stablecoin
supply/velocity.

**2. Staking yield / validator queue depth.**
For proof-of-stake assets where this applies (ETH primarily), track real
staking yield (post-issuance, i.e. net of the rate at which new supply is
created) and activation/exit queue depth via an official/documented source
(e.g. beaconcha.in's API, or the consensus-layer client APIs if a hosted
beacon-node endpoint is already in reach). Verify real access before
committing. Store as `STAKING_YIELD_AND_QUEUE_DEPTH`, registered in
`signal_sources`. BTC-equivalent assets have no staking mechanism — this
source is scoped to PoS assets only, same "doesn't transfer to the whole
universe" treatment 3c gave BTC miner metrics.

**3. Stablecoin depeg-risk monitoring.**
Track a curated set of major stablecoins' price deviation from their peg
across the venues already integrated (3b/3c), distinct from 3c's supply/
velocity tracking. This is a monitoring/flagging signal, not a
`source_assessment` directional input — its output surfaces as a risk flag
(e.g. alongside 3h's stress-test output and 3j's exchange-counterparty-risk
flag, if implemented) rather than something the Judge weighs for directional
calls. Register as `STABLECOIN_DEPEG_RISK` in `signal_sources`.

**4. Tests & docs.**
`pytest` passes without live credentials for whichever source(s) are
implemented. Update `README.md`: document which source(s) cleared the gate
and why (citing the specific 3g/3h finding), which were skipped and why,
the feasibility-check outcome per source, cost, and the follow-up
calibration/evidence-value re-run result.

## Exit criteria

- The gate section above is explicitly addressed in the README before any
  code exists — which finding motivated which source, or a statement that
  the gate was not met and 3k was deliberately skipped in full.
- Any implemented source is feasibility-verified, registered in
  `signal_sources`, wired into the Judge as a distinct labeled input (or, for
  stablecoin depeg risk, as a distinct risk-report flag), and cost-documented.
- Follow-up calibration/evidence-value re-run completed for any implemented
  source, with the same provisional framing as 3f/3i/3j.
- `pytest` green without credentials.
- README updated with real findings, not placeholders — including an
  explicit "skipped, gate not met" statement for any source not implemented.

Report the gate evaluation (met/not met, and for which sources), whatever
was actually implemented as a result, and wait for confirmation before
proceeding to Phase 4 (or, if 3j and 3k are both still pending, before
proceeding past whichever of the two is resolved last).
