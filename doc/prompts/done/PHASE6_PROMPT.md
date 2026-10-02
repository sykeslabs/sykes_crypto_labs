# AI Crypto Portfolio — Phase 6: Exchange Execution Agent (Testnet Only)

## Context

Phase 5 gives the project a read/query API and dashboard over everything
built so far. Phase 6 is the only agentic component in the entire system:
it takes Portfolio Construction's already-approved target allocation
changes and turns them into actual orders against a **testnet/sandbox**
exchange API — not a simulation this time, a real external system, just one
that trades with fake funds.

**Before writing any code**, inspect what actually exists: Portfolio
Construction's real output shape (3e), Risk Engine's constraint-checking
logic (3e, callable again rather than only inline), Phase 4's fill
simulator and its `assumed_fill_method` labeling, and 3b/3c's existing
Binance/Coinbase client code (a testnet often shares most of its request
shape with the production API those clients already call). This phase does
**not** change Judge/Risk Engine/Portfolio Construction decision logic — it
consumes their already-approved output and is the first stage in this
project that calls an external system with side effects, rather than only
reading market data or calling an LLM.

**This task is Phase 6 only.** There is no Phase 7 defined yet. Stop after
Phase 6 is verified and wait for confirmation before any discussion of real
(non-testnet) trading — which, per this project's own development
methodology, requires a separate, explicit safety review and is not
something this prompt authorizes or scopes.

## Why an agent framework, here and only here

Every stage through Phase 5 is a fixed, deterministic pipeline: structured
JSON in, structured JSON out, no decision-making left to a runtime loop.
Interacting with a live exchange API is different in kind, not just degree:
placing an order, checking whether it actually filled, and potentially
cancelling or adjusting it is exactly the bounded, tool-using loop an agent
framework exists for. That's the entire justification for introducing
LangChain/LangGraph now, after five phases of deliberately not needing one
— and it's also exactly why this phase carries more constraints than any
prior one, not fewer. An agent that decides *how* to place an order is a
much smaller trust surface than an agent that decides *whether* to trade;
this phase must not blur that line.

## Non-negotiables

- **TESTNET ONLY.** Every credential configured in this phase must be
  testnet/sandbox-scoped. Real production API keys must never be
  configured, read, or reachable from this phase's code path. Real
  (non-testnet) trading remains gated behind a separate, explicit safety
  review per this project's development methodology — this phase does not
  perform that review and does not unlock real trading by existing.
- **The agent does not make trading decisions.** Its only input is a
  Portfolio Construction target change that has *already* cleared Judge +
  Risk Engine — never an open-ended instruction, never raw market data,
  never a fresh chance to reconsider the decision itself. If Portfolio
  Construction didn't approve it, the agent cannot act on it.
- **Explicit, allow-listed toolset only:** `place_order`, `cancel_order`,
  `check_order_status`, `check_balance` — nothing else. No dynamic tool
  discovery, no generic HTTP/API-call tool, no ability for the agent to
  invoke anything outside this fixed list.
- **Risk Engine constraints are re-checked at execution time, not just
  recommendation time.** Time elapses between a Judge decision and its
  execution; price/volatility can move enough in that window that the
  original approved size no longer satisfies `MAX_SINGLE_ASSET_ALLOCATION`/
  `MAX_NEW_POSITION_SIZE`/etc. Re-validate against current market state
  immediately before calling `place_order`, and resize or reject rather than
  execute a now-stale approval unchanged.
- **Idempotent, deduplicated order placement.** Every target change gets a
  stable idempotency key; re-invoking the agent for the same approved change
  (e.g. after a crash or manual retry) must not result in a duplicate order.
  Verify via `check_order_status`/`check_balance` before assuming a retry is
  safe, never assume "it probably didn't go through."
- **Bounded execution, with a real, enforced timeout — this project has
  already had a real, hours-long hang from an unbounded wait, and that
  failure mode is far more serious here than it was for an LLM call.** Every
  agent invocation has an explicit wall-clock timeout. On breach, the
  invocation is marked `TIMED_OUT`, and the system explicitly reconciles
  real exchange state (via `check_order_status`/`check_balance`) before
  deciding what actually happened — a timeout must never be treated as
  "nothing happened," since the order call may have already reached the
  exchange before the timeout fired.
- **No assumed fills.** An order is only ever considered filled, partially
  filled, or cancelled based on a real, queried response from
  `check_order_status`/`check_balance` — never inferred from
  `place_order`'s initial response alone, never assumed from elapsed time.
- **A kill switch, checked before every tool call.** A single
  env/DB-configured flag that, when set, halts all agent action
  immediately — plus an automatic circuit breaker that halts the agent after
  a small number of consecutive tool-call failures, rather than retrying
  indefinitely against a failing exchange API.
- **Full audit trail.** Every tool call this agent makes — arguments, raw
  response, timestamp — is persisted, not just logged to console. This is
  the first phase where the system takes real external action; the ability
  to reconstruct exactly what happened, in order, is not optional.
- **Never expose secrets.** Same standard as Phase 5: testnet API
  keys/secrets must never appear in a response body, log line reachable via
  the Phase 5 API, or error message.
- **Live verification is required, not optional** — same standard as every
  prior phase, and especially this one: before Phase 6 is reported complete,
  the agent must have placed, and correctly reconciled, at least one real
  order against the actual testnet API (not a mocked client), including a
  deliberately-triggered cancellation and a deliberately-triggered
  duplicate-invocation attempt confirmed *not* to double-place.

## Task detail

**1. Testnet exchange selection & feasibility check.**
Verify real, documented testnet/sandbox API access — order placement,
cancellation, balance query, order-status query — for whichever of
Binance/Coinbase (already integrated in 3b/3c) offers a genuine sandbox
environment, same feasibility-check discipline as every prior sub-phase.
Document credential setup, and how testnet credentials are kept structurally
separate from any future production credential (e.g. distinct env var names,
never a shared `.env` block with production keys once those might exist).

**2. Bounded execution agent (`app/execution/`).**
A LangGraph agent with the fixed toolset above, consuming Portfolio
Construction's approved target changes and re-checking Risk Engine
constraints at execution time (call the existing Risk Engine logic again,
don't reimplement it). Implements the idempotency, timeout, kill-switch, and
audit-trail non-negotiables above as first-class parts of the execution
loop, not bolted on after.

**3. Fill reconciliation against Phase 4's assumptions.**
For every real testnet fill, compare the actual fill price/slippage against
Phase 4's fill-simulator prediction (`assumed_fill_method`,
`DEPTH_WALKED`/`VOLATILITY_SCALED_ESTIMATE`) made for that same target
change. Persist the comparison as a distinct, clearly-labeled finding — this
either validates or challenges Phase 4's fill assumptions with real data,
and should be reported that way (a finding, not a silent correction), same
standing as 3h/3g's diagnostic-only additions.

**4. Tests & docs.**
`pytest` passes without live credentials: mocked-exchange-client tests
covering normal placement/cancellation, a simulated timeout confirmed to
resolve to `TIMED_OUT` with correct state reconciliation (not left
indefinitely running), and a simulated duplicate-invocation confirmed not to
double-place. Update `README.md`: mark Phase 6 complete, document the
testnet exchange chosen and why, the real order(s) placed/cancelled during
live verification, and the fill-reconciliation finding against Phase 4.

## Exit criteria

- Testnet exchange access is feasibility-verified and documented; testnet
  credentials are structurally separate from any future production
  credential.
- The agent's toolset is exactly `place_order`, `cancel_order`,
  `check_order_status`, `check_balance` — no broader access exists.
- The agent only ever acts on an already-approved Portfolio Construction
  target change; there is no code path by which it can originate or modify a
  trading decision.
- Risk Engine constraints are demonstrably re-checked at execution time
  (e.g. a test/fixture shows a stale approval correctly resized or rejected
  due to simulated intervening price movement).
- A real duplicate-invocation attempt against the live testnet API is
  confirmed not to double-place an order.
- A real timeout scenario (simulated or naturally occurring) is confirmed to
  resolve to `TIMED_OUT` with exchange state correctly reconciled afterward,
  not left indefinitely running.
- The kill switch, checked live, halts agent action when set.
- Every tool call made during live verification is persisted with full
  arguments/response/timestamp, confirmed queryable afterward.
- No secret ever appears in a response, log, or error path — verified by an
  explicit test.
- At least one real order has been placed and correctly reconciled against
  the live testnet API, and at least one real cancellation, during live
  verification — not fixture tests alone.
- Fill reconciliation against Phase 4's simulator assumptions is computed
  and reported as a distinct, labeled finding for at least one real fill.
- `pytest` green without live credentials.
- README updated with real findings, not placeholders.

Report the testnet exchange chosen, the real orders placed/cancelled during
verification, the fill-reconciliation finding, and confirmation that every
non-negotiable above was checked live rather than assumed. This is the last
phase currently scoped in this project — there is no default next step, and
any discussion of real trading requires an explicit, separate safety review
before any further scoping begins.
