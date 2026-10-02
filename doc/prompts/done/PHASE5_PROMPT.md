# AI Crypto Portfolio — Phase 5: Read/Query API, Scheduling & Dashboard

## Context

Phase 4 is complete: a deterministic Judge/Risk Engine/Portfolio Construction
pipeline produces paper-only recommendations, execution is simulated with
realistic fees/slippage, and 3g/3h/Phase 4 together give a statistically-honest
(if still data-limited) picture of accuracy, calibration, and cost impact.
Every run so far has been triggered manually via CLI flags
(`--with-screening`, `--with-assessment`, `--with-judge`, etc.), and every
piece of state (candidates, assessments, decisions, portfolio, cost, evidence
feasibility) lives in Supabase with no way to see it except direct queries.

**Before writing any code**, inspect what actually exists: the real shape of
every table this phase reads from (`judge_decisions`, `decision_outcomes`,
`model_market_assessments`, `signal_sources`, `calibration_runs`,
`evidence_value_reports`, `adversarial_research`, `judge_reasoning_audits`,
the CostGuard-tracked tables), and the Pydantic schemas already defined for
their contents in Phase 2/3/4 code. This phase is a **read/query and
orchestration layer over already-existing state** — it does not add new
evidence sources, does not change Judge/Risk Engine/Portfolio Construction
decision logic, and does not place any order (real or testnet — that's
Phase 6).

**This task is Phase 5 only.** Do not begin Phase 6 (exchange execution
agent). Stop after Phase 5 is verified and wait for confirmation.

**Deployment scope — decide explicitly before building.** This phase's
security bar depends entirely on how reachable the API/dashboard actually
is. Localhost/personal-machine-only access and a genuine public deployment
are different problems with different acceptable minimums — a single
API-key header may be a reasonable bar for the former and clearly
under-scoped for the latter (which would also need TLS and a much louder
warning than "not full production auth"). State which one this phase
targets in the README before implementation, not after.

**Two known data gaps this dashboard will immediately surface — not bugs.**
Inspecting what exists (per the instruction above) will show: (1)
`regime_at_decision` is `NULL` on all 109 resolved decisions (3e.1's
backfilled set never persisted a real `market_regime_snapshots` row — a
known 3g/3h finding), so the "hit-rate/Brier by regime" view has nothing
real to display against the only resolved dataset that currently exists;
and (2) zero live (non-backfilled) decisions have resolved yet, so any
live-only calibration view will correctly show null/insufficient-data by
design. Both should render as honest empty/insufficient-data states,
identical in spirit to 3g/3h/3e.1's own null findings — not something to
work around, paper over, or mistake for a dashboard bug during
verification.

## Why this phase exists, and why it's not just a UI wrapper

Every prior phase's output has only ever been inspected by querying Supabase
directly or reading CLI logs — including, this project's own history shows,
by manually reconciling numbers across CLI output, Supabase, and a third-party
billing dashboard to catch real bugs (the 3c `signal_sources` staleness gap,
the 3e.1 CostGuard blind spot, the 3f/3g evidence-dedup bugs). That
manual-reconciliation discipline worked, but it doesn't scale as a permanent
way to operate this system, and it's exactly the kind of toil a read/query
layer should remove — **without removing the underlying verification habit**.
Phase 5's dashboard should make the real state of the system (including its
known limitations, nulls, and honestly-reported gaps) *more* visible and
harder to misread, not smoothed over into a falsely reassuring UI.

## Non-negotiables

- **Read-only over existing decision logic.** No endpoint may trigger a
  trade, alter a `judge_decisions`/`decision_outcomes` row's substantive
  content, or bypass Risk Engine constraints. The API queries and
  orchestrates existing pipeline runs; it does not gain a new way to decide.
- **Reuse existing Pydantic schemas** (`JudgeDecisionItem`, assessment/
  adversarial output models, etc.) as FastAPI response models rather than
  redefining parallel shapes — this is the specific, stated reason FastAPI
  was chosen for this project over alternatives.
- **Never expose secrets.** `SUPABASE_SERVICE_ROLE_KEY`, `OPENROUTER_API_KEY`,
  `DATABASE_URL`, and any other credential must never appear in a response
  body, error message, log line reachable via an endpoint, or dashboard
  payload — including in stack traces on a 500. Add a test that
  deliberately triggers an error path and asserts no configured secret
  substring appears in the response.
- **Basic access control from day one.** This is the first component in the
  project that's reachable over the network rather than run locally via CLI.
  A simple API-key-header check (env-configured, documented, not a full
  OAuth/user-account system) is the minimum bar — do not ship an
  unauthenticated read layer over portfolio/cost data, even for a
  personal/paper-only project.
- **Cost/spend reporting must reconcile, not just display.** This project has
  twice now had a real gap between what the app's own ledger reported and
  what was actually true (3e.1's CostGuard blind spot; the OpenRouter
  account-vs-key-limit confusion in 3f). The cost-reporting endpoint/
  dashboard view must show CostGuard's internal `COST_TRACKED_TABLES` sum
  **and**, where feasible, note explicitly that this is the app's own
  tracked spend, not a live provider-billing balance — don't imply the two
  are guaranteed to match.
- **Point-in-time integrity applies to historical queries too.** Any
  endpoint that answers "what did the system know/decide as of date X" must
  use 3a's `as_of`/point-in-time convention against revisable evidence, not
  a naive latest-value join — the same discipline 3g's audit already
  verified at the pipeline level must not be silently broken by a
  convenience query at the API layer.
- **Scheduling must not repeat this project's own hang/cost incidents.** If
  task 3 (below) is implemented, every scheduled run must: (a) still pass
  through the existing CostGuard pre-call check unmodified, (b) enforce an
  explicit wall-clock timeout per run with the run marked `FAILED`/`TIMED_OUT`
  on breach — not left indefinitely "running" — and (c) persist a real,
  queryable job-history record (start, end, status, real cost) so a stuck or
  runaway job is visible from the API/dashboard, not only discoverable via a
  manual `ps`/process check the way this session's hangs had to be resolved.
- **Backfilled, provisional, and null findings stay visibly distinct in the
  UI.** 3e.1's backfilled vs. live baselines, 3g's honest null calibration
  attempts, 3h's "insufficient data" results, and Phase 4's mark-to-mid vs.
  net-of-costs figures must never be merged, averaged, or displayed as a
  single number in the dashboard — each retains the same explicit labeling
  it has in the database. A dashboard that quietly collapses these into one
  clean-looking figure would undo the entire point of tracking them
  separately.
- **No agentic behavior.** Scheduling triggers existing, already-deterministic
  pipeline invocations on a timer — it is not a decision loop, and it must
  not gain any tool-use/agent framework. That remains scoped to Phase 6's
  execution agent only.
- **Live verification is required, not optional.** Every prior phase's real
  bugs (3c's `signal_sources` staleness gap, 3e.1's CostGuard blind spot, the
  3f/3g/3h evidence-dedup and persistence-gap bugs) were caught by checking
  actual behavior against the live Supabase project, never by a green
  fixture-test suite alone. Passing `pytest` against fixtures is necessary
  but not sufficient here: before this phase is reported complete, every
  endpoint must be exercised against the real, live Supabase project with at
  least one real, known value confirmed end-to-end (e.g. a specific real
  `judge_decisions` row's thesis appears correctly via its endpoint) — not
  just "the server starts and returns 200."

## Task detail

**1. FastAPI read/query layer (`app/api/`).**
Endpoints covering, at minimum:
- Screening universe & candidates (3b): current `TOP_CANDIDATES`, full
  screened universe, regime snapshot, composite factor scores.
- Model assessments (3d) and adversarial research (3f): per-asset,
  per-model output, `model_agreement`.
- Judge decisions (3e) and reasoning audits (3g): full decision record
  (thesis, key/contradictory evidence, invalidation conditions), plus audit
  results where they exist.
- Portfolio state (3e/Phase 4): current holdings, target allocations,
  simulated fills, mark-to-mid vs. net-of-costs performance, and each
  fill's `assumed_fill_method` (`DEPTH_WALKED` vs.
  `VOLATILITY_SCALED_ESTIMATE`) surfaced explicitly per fill — Phase 4
  built this specifically to make a previously-hidden assumption visible,
  and this dashboard should not silently hide it again.
- Decision-outcome ledger & calibration (3e/3g/3h): resolved/unresolved
  counts, hit-rate/Brier by regime and agreement bucket, DSR/PBO results,
  held-out-window status, evidence-value rankings — each tagged with its
  real sample size and backfilled/live/provisional status, never hidden.
- `signal_sources` status: every source's real `NOT_IMPLEMENTED`/
  `UNAVAILABLE`/live status and notes, exactly as stored — this project has
  a real, hard-won history of sources silently going stale (3c) or being
  wrongly assumed available; the dashboard should make current status
  trivially checkable without a manual query.
- Cost/spend reporting: `COST_TRACKED_TABLES` sums by table/day/month
  against configured caps.

All endpoints are read-only (`GET`); no endpoint accepts a body that alters
decision-relevant state.

**2. Access control.**
A single configured API key (env var, e.g. `API_ACCESS_KEY`) required via
header on every endpoint except a basic health check. Document this plainly
as a minimum bar, not a claim of production-grade auth.

**3. Scheduling (optional within this phase — decide and document, don't
default silently).**

**Practical note, not a scope item:** if this task requires a new migration
(e.g. a job-history table), expect the same snag every migration since 0011
has hit — `scripts/apply_migration.py`'s configured `DATABASE_URL` password
is stale, so manual application via the Supabase SQL Editor has been the
working path every time. Plan for that rather than re-diagnosing it fresh.

If included: a lightweight recurring-run mechanism (e.g. APScheduler, or a
documented external cron entry point calling the existing CLI) that invokes
the pipeline's already-existing flags on an interval. Must satisfy every
scheduling non-negotiable above. If you decide scheduling isn't worth adding
yet (e.g. still manually triggering runs while data accumulates toward 3h's
sample-size threshold), document that reasoning explicitly, same as 3e.1/3h's
"considered, deferred" write-ups — this is a real decision point, not a
default yes.

**4. Minimal dashboard.**
A simple read-only frontend (server-rendered or a lightweight SPA — pick
whichever is less work, this is not the place for new frontend-stack
decisions) presenting: current portfolio state, recent Judge decisions with
full reasoning, calibration/accuracy figures (correctly separated per the
non-negotiables above), `signal_sources` status, and cost/spend status
against caps.

**5. Tests & docs.**
`pytest` passes without live credentials: endpoint tests against fixture
data, an explicit test that no secret substring leaks via any error path, and
(if scheduling is implemented) a test proving a simulated hung job is
correctly marked `TIMED_OUT` rather than left running indefinitely. Update
`README.md`: mark Phase 5 complete, document which endpoints exist, the
access-control mechanism, the scheduling decision (implemented or explicitly
deferred, with reasoning), and any real findings from wiring the dashboard up
against live data.

## Exit criteria

- Deployment scope (localhost-only vs. public) is explicitly stated in the
  README before implementation, and the access-control approach matches
  whichever was chosen.
- FastAPI endpoints exist for candidates/screening, assessments, adversarial
  research, Judge decisions, portfolio state (including per-fill
  `assumed_fill_method`), calibration/evidence-value results,
  `signal_sources` status, and cost/spend — all read-only, all using
  existing Pydantic schemas.
- Every endpoint has been exercised against the live Supabase project with
  at least one real, known value confirmed end-to-end — not fixture tests
  alone.
- The regime-NULL and zero-resolved-live-decisions gaps render as honest
  empty/insufficient-data states in the dashboard, confirmed live, not
  mistaken for bugs during verification.
- No endpoint or error path ever returns a configured secret, verified by an
  explicit test.
- API access requires a configured key; this is documented as a minimum bar,
  not full production auth.
- The scheduling decision (build now vs. defer) is explicit and reasoned in
  the README, not silently skipped or silently added.
- If scheduling is implemented: every run passes through the existing
  CostGuard check, enforces a wall-clock timeout with a real `TIMED_OUT`
  status on breach, and persists a queryable job-history record.
- The dashboard displays backfilled/live/provisional/null findings as
  visibly distinct, never merged into one figure.
- `pytest` green without live credentials.
- README updated with real findings, not placeholders.

Report which endpoints were built, the access-control and scheduling
decisions with reasoning, and any real findings from live-wiring the
dashboard, and wait for confirmation before starting Phase 6 (exchange
execution agent, testnet only).
