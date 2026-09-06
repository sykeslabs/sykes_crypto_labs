# AI Crypto Portfolio — Phase 3j: Deferred Evidence Backlog (Gated, Optional)

## Context

This is a **third** gap-analysis addendum, following the same pattern as 3h
(adaptive evidence-value weighting, stress testing) and 3i (entity-flow,
custody/OTC, network fundamentals) — both of which were added after
comparing this project against professional crypto-advisory practice. This
pass surfaced three more candidate signal sources:

1. **Options gamma exposure / dealer positioning** (a distinct signal from
   3c's options IV/skew and volatility risk premium — this is about
   mechanical price pinning/acceleration from dealer hedging flow near large
   open-interest strikes, not sentiment).
2. **Exchange counterparty/solvency risk** — proof-of-reserves attestations
   and exchange insurance-fund levels, as a monitor for the specific
   recurring crypto tail risk of exchange insolvency/contagion (FTX-style),
   distinct from every market/on-chain signal already collected.
3. **Retail-demand proxies** — search-interest (e.g. Google Trends for
   asset/exchange terms) and exchange-app-store-rank tracking, as a cheap,
   early indicator of retail-driven speculative spikes, complementary to
   3f's `SOCIAL_NARRATIVE_SENTIMENT`.

**Unlike every other Phase 3 sub-phase, 3j is not scheduled by default.**
This project's own stated methodology is explicit: *"new tooling earns its
place by matching a real need, not by being available"* (README,
Development methodology). At the time this addendum was written, there is
no evidence that the existing evidence set (3a–3i) is under-performing in a
way these three sources would fix — they were identified by comparing
against what professional desks *have available*, not by any finding that
this system's accuracy or calibration is currently limited by their
absence. Adding them speculatively would mean shipping three more
cost-bearing, drift-prone inputs into a system whose own 3g/3h machinery
exists specifically to catch overfitting from exactly this kind of
feature-creep.

## Gate — read before doing anything else

**Do not start implementation work on 3j until both of the following are
true, and document that they're true before writing code:**

1. **3h's evidence-value ranking has run** (full-history and rolling/
   regime-sliced) against a real `decision_outcomes` history large enough to
   clear its own minimum-sample-size threshold — not "insufficient data."
2. **That ranking shows a specific, named gap** these three sources would
   plausibly close — e.g. "the Judge is repeatedly wrong-footed by
   short-horizon volatility spikes around known large-OI options
   expiries, and no current source explains why" (→ motivates gamma
   exposure), or "3g's Judge-reasoning audit or 3h's drift check surfaces a
   recurring blind spot around retail-driven speculative moves" (→
   motivates retail-demand proxies), or "a specific historical drawdown in
   the stress-test scenarios (3h task 2) was exchange-solvency-driven and
   the system had no leading indicator for it" (→ motivates counterparty
   risk monitoring).

If neither condition holds, the correct action is to **not implement 3j**,
full stop — not to implement "the easy one anyway." Revisit this gate
periodically as more `decision_outcomes` history accumulates in Phase 4,
rather than treating "not now" as "never."

If the gate is met for only one of the three sources, implement only that
one — 3j is not an all-or-nothing sub-phase like 3b/3c were.

## Non-negotiables (apply to whichever source(s) clear the gate)

- PAPER ONLY.
- Same feasibility-check discipline as 3f: verify real, documented
  programmatic access before writing any collector code. Record
  `UNAVAILABLE`/`NOT_IMPLEMENTED` in `signal_sources` for anything that
  doesn't check out, same as every prior sub-phase.
- Each source ships with the same cost-sizing discipline as every other
  sub-phase: a documented dollar cost (if any paid tier is required) against
  project budget, and zero new LLM cost unless explicitly justified and
  `CostGuard`-gated.
- Each source is wired into the Judge as a distinct, labeled
  `source_assessment` entry — never blended into `confidence` or any other
  source's value, same standing as every other evidence type in this
  project.
- Because this sub-phase is gated on a specific named finding (see above),
  each source's README write-up must explicitly reference which 3h/3g
  finding motivated it — not just "this is a source professional desks use."
- After implementation, re-run 3g-style calibration and 3h-style
  evidence-value ranking specifically for the new source, with the same
  "provisional, not a confirmed improvement" framing 3f/3i used — closing
  the loop on whether the named gap was actually closed, not just assuming
  it was because the source is now present.

## Task detail (implement only sources that cleared the gate)

**1. Options gamma exposure / dealer positioning.**
Distinct from 3c's Deribit IV/skew: this is derived from the open-interest
distribution across strikes (available from the same Deribit options data
already scoped in 3c, or a documented aggregator such as Amberdata/Genesis
Volatility if strike-level OI isn't cleanly derivable from Deribit's public
endpoints alone). Verify real access to strike-level OI before committing to
an implementation approach. Store as a new evidence type,
`OPTIONS_GAMMA_EXPOSURE`, registered in `signal_sources`.

**2. Exchange counterparty/solvency risk.**
Proof-of-reserves attestations (where major exchanges publish them) and, if
programmatically accessible, exchange insurance-fund balances. This is a
monitoring/flagging signal, not a predictive-return signal in the same
sense as the others — its main use is a risk flag (e.g. surfaced alongside
3h's stress-test output) rather than a `source_assessment` input the Judge
weighs for directional calls. Verify what's actually publicly/
programmatically available per exchange before committing to scope; this is
likely to be the most feasibility-constrained of the three. Register as
`EXCHANGE_COUNTERPARTY_RISK` in `signal_sources`.

**3. Retail-demand proxies.**
Google Trends (via its public/unofficial API — verify current access terms
and reliability before committing, same feasibility-gating as 3f's
fragile sources) for asset/exchange search terms, and/or exchange-app
store-rank tracking where a documented API exists. Register as
`RETAIL_DEMAND_PROXY` in `signal_sources`, grouped with 3f's fragile/
feasibility-gated sources given similar access-reliability uncertainty.

**4. Tests & docs.**
`pytest` passes without live credentials for whichever source(s) are
implemented. Update `README.md`: document which source(s) cleared the gate
and why (citing the specific 3h/3g finding), which were skipped and why,
the feasibility-check outcome per source, cost, and the follow-up
calibration/evidence-value re-run result.

## Exit criteria

- The gate section above is explicitly addressed in the README before any
  code exists — which finding motivated which source, or a statement that
  the gate was not met and 3j was deliberately skipped in full.
- Any implemented source is feasibility-verified, registered in
  `signal_sources`, wired into the Judge as a distinct labeled input (or, for
  counterparty risk, as a distinct risk-report flag), and cost-documented.
- Follow-up calibration/evidence-value re-run completed for any implemented
  source, with the same provisional framing as 3f/3i.
- `pytest` green without credentials.
- README updated with real findings, not placeholders — including an
  explicit "skipped, gate not met" statement for any source not implemented.

Report the gate evaluation (met/not met, and for which sources), whatever
was actually implemented as a result, and wait for confirmation before
proceeding to Phase 4. If the gate was not met for any source, the expected
and acceptable outcome of this sub-phase is "no new code, gate re-evaluated
later" — treat that as a valid, successful outcome of 3j, not as an
incomplete task.
