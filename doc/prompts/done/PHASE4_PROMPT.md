# AI Crypto Portfolio — Phase 4: Paper Trading Execution, Benchmarks, Ongoing Accuracy Tracking

## Context

Phase 3 (3a–3i, plus 3j if its gate was met) is complete: a deterministic
Judge/Risk Engine/Portfolio Construction pipeline produces paper-only
recommendations, a decision-outcome ledger tracks them against realized
market data, and 3g/3h have delivered a statistically-honest calibration
and stress-test picture with a held-out window respected throughout.

**Before writing any code**, inspect what actually exists: the real
`decision_outcomes` evaluation logic from 3e (triple-barrier-style
HIT_TARGET/HIT_STOP/TIMED_OUT backfilling against `market_snapshots`), 3g's
go/no-go statement, and 3h's stress-test module. Phase 4 does not change
Judge/Risk/Portfolio decision logic — it builds the execution-simulation and
benchmarking layer *underneath* the decisions those already produce.

**This task is Phase 4 only.** Do not begin Phase 5 (dashboard/API) or
Phase 6 (testnet execution agent). Stop after Phase 4 is verified and wait
for confirmation.

## Why this phase exists, and why it's not just bookkeeping

3g's calibration numbers (Brier score, hit-rate, Deflated Sharpe) are all
computed against `decision_outcomes.realized_return`, which up to this point
is derived from **mark-to-mid** `market_snapshots` prices — i.e. it assumes
every recommended trade fills instantly at the mid price with no cost. That
assumption doesn't just slightly understate real-world performance; it
means every accuracy/calibration claim produced so far describes a system
that cannot actually be traded as evaluated. Phase 4's job is to make the
paper-trading simulation execution-realistic enough that its own tracked
performance is an honest estimate of what live paper (and eventually
testnet) trading would show — not a second, unrelated feature.

## Non-negotiables

- PAPER ONLY. No live exchange credentials, no live orders — this phase
  simulates fills against real market data, it does not place them.
- **Fills are not mark-to-mid.** Every simulated fill must account for:
  - **Trading fees**, using each source exchange's actual documented maker/
    taker fee schedule (Binance/Coinbase, per 3b's exchange-native
    collectors) rather than a single guessed flat rate.
  - **Slippage from order-book depth**, not a flat percentage. Collect (or
    reuse, if 3b/3c already retrieves it) order-book depth data — e.g.
    Binance/Coinbase's public order-book/depth endpoints — at a resolution
    sufficient to estimate the volume-weighted average execution price for
    a given order size, rather than assuming unlimited liquidity at the top
    of book. Where depth data isn't available for a given asset/timeframe,
    fall back to a documented, clearly-labeled volatility-scaled slippage
    estimate (e.g. a multiple of recent realized volatility, scaled by
    order size relative to typical volume) — label it as an estimate, not
    measured depth, the same "don't fabricate, label the assumption"
    discipline 3h used for cross-asset stress-test proxies.
  - **Partial fills / size limits**: a simulated order larger than available
    depth at a reasonable number of order-book levels should not fill
    entirely at one price — model at least a simple multi-level walk of the
    book, even if simplified.
- This phase must not retroactively alter `in_holdout_window` tagging or any
  already-reported 3g/3h finding. It changes how *future* decisions are
  evaluated and, if useful, re-evaluates historical ones with execution
  costs applied as a **separate, clearly-labeled** comparison — not a
  silent replacement of 3g's original numbers.
- Every new fee/slippage-adjusted return is stored alongside, not instead
  of, the original mark-to-mid figure — so "how much did execution
  realism cost us" is itself a reportable number.
- Point-in-time integrity (3a's non-negotiable) applies here too: simulated
  fills must use order-book/price data as it existed at the simulated
  decision/fill time, never a since-revised or future value.

## Task detail

**1. Order-book-aware fill simulator (`app/trading/`).**
Given a Judge/Risk-Engine-approved target allocation change (buy/sell/
rebalance) and a simulated execution time, compute a realistic fill price:
fee-adjusted, depth-aware slippage as described above, with the assumption
set (flat top-of-book vs. depth-walked vs. volatility-scaled fallback)
recorded per fill so later analysis can see which assumption was used where.

**2. Extend `decision_outcomes` evaluation.**
Add fee/slippage-adjusted realized-return fields alongside the existing
mark-to-mid `realized_return` (e.g. `realized_return_net_of_costs`,
`assumed_fill_method`). Re-run 3g's calibration/reliability report using the
net-of-costs figures as a second, explicitly-labeled comparison against the
original — report both, and be explicit about how much the accuracy/
calibration picture changes once execution costs are included. A material
change here is itself an important finding, not a footnote.

**3. Benchmark tracking (`app/benchmarks/`).**
Track portfolio performance against at least two naive baselines: equal-
weight-across-universe and BTC buy-and-hold, computed with the same
fee/slippage treatment as the system's own simulated fills (an unfair
comparison — costed system vs. costless baseline — would silently favor the
baseline). Report risk-adjusted performance (Sharpe, max drawdown) for the
system and both baselines over the same period.

**4. Portfolio-construction sizing review (deferred decision, not
assumed).**
3e's inverse-vol/capped-Kelly sizing was deliberately kept simple for a
pre-execution-realism paper system. Now that realistic fills/costs exist,
decide — and document the reasoning either way — whether a fuller
portfolio-optimization step (e.g. risk parity, a constrained mean-variance
step) is worth the added complexity given the turnover/fee costs now
visible from task 1–3. This is a decision to make explicitly here, not a
default "yes, add it" — added complexity has its own overfitting risk, same
philosophy as 3j's gating.

**5. Tests & docs.**
`pytest` passes without live credentials: fill-simulator tests against
fixture order-book snapshots with a known expected VWAP/slippage outcome,
and a fixture case exercising the volatility-scaled fallback path. Update
`README.md`: mark Phase 4 complete, report the net-of-costs calibration
comparison, the benchmark results, and the sizing-review decision and its
reasoning.

## Exit criteria

- Fill simulator produces fee- and depth-aware execution prices, with the
  assumption method recorded per fill.
- `decision_outcomes` carries both mark-to-mid and net-of-costs realized
  returns, and 3g's calibration report has been re-run on both, with the
  delta between them explicitly reported.
- Benchmark tracking reports system vs. equal-weight vs. BTC buy-and-hold,
  all under the same cost treatment.
- The portfolio-optimization sizing question (task 4) is explicitly
  answered with documented reasoning, not silently deferred again.
- `pytest` green without credentials.
- README updated with real numbers, not placeholders.

Report the net-of-costs calibration findings, the benchmark comparison, and
the sizing-review decision, and wait for confirmation before starting
Phase 5 (FastAPI read/query layer + dashboard).
