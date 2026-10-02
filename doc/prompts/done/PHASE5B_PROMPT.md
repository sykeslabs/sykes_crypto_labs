# Phase 5b (proposed) — Dashboard UX pass for a non-financial end user

Not yet scoped as an official phase — a draft prompt to review and adjust
before treating it as one. Follows this project's standing methodology
(read in full, live-verify against the real running system, update docs
with real findings, no fabricated data) once picked up.

## Context

Phase 5's dashboard (`app/api/static/dashboard.html`) was built to prove
the read/query API works — plain HTML tables, vanilla JS, no framework,
"pick whichever is less work." That was the right call for Phase 5's own
scope. It was never designed for a non-financial end user to actually use
day to day, and by now (post-5a and this session's small fixes) it covers
real ground: service health (Signal sources), current vs. recommended
portfolio composition (Real holdings vs. Portfolio state), the Judge's
reasoning (Recent Judge decisions), accuracy tracking (Calibration
summary), and real spend (Cost / spend).

The end user for this pass is explicitly a non-financial person who wants
to open one page and answer, in order: *what do I actually hold, what does
the AI think I should hold, why, is anything broken, and what is this
costing me.* Everything below is organized around that reading order
rather than around the six existing panels as a flat list.

The goal of this pass is presentation, not content. Every number, every
caveat, every honest "n/a"/"insufficient data"/`NOT_IMPLEMENTED` state that
exists today must still be reachable afterward — this is about making it
legible to someone who doesn't already know what a Sharpe ratio or a Brier
score is, not about hiding complexity or deciding what they don't need to
see. Anywhere this project already went out of its way to disclose a real
limitation (regime-NULL, zero-resolved-live-decisions, N+1 latency,
paid-tier deferrals), the same disclosure needs to survive in the new
design, not get quietly dropped for the sake of a cleaner-looking screen.

## Non-negotiables (same discipline as every prior phase)

- No content removed, none hidden behind an extra click that used to be
  free. Reorganizing, re-labeling, and re-visualizing is the point;
  deleting a data point or caveat because it's inconvenient to display is
  not in scope.
- No new fabricated numbers. If a nicer visualization needs a number the
  API doesn't currently expose (e.g. a time series for a trend line),
  that's a new backend endpoint problem to solve for real, not a
  client-side approximation.
- Live-verify in an actual browser before calling this done — this
  project has been burned once already by a dashboard bug that only a
  real browser (not a headless substitute) could have caught immediately.
- Keep the "no framework" bar honest, not just default. If a chart needs a
  real charting approach, evaluate a small, dependency-light option (e.g.
  native `<canvas>`/inline SVG, or a single vendored library) against the
  actual maintenance cost of writing pie/line charts by hand — don't reach
  for a full frontend framework by default, but don't rule one out on
  principle if the honest answer is that hand-rolled SVG is worse to
  maintain.
- Still localhost/personal-machine scope (Phase 5's deployment decision
  stands) — this is a UX pass, not a re-litigation of hosting.
- No jargon left unexplained on first read. If a term (Sharpe ratio, Brier
  score, mark-to-mid, regime) appears anywhere in the UI, a first-time
  viewer must be able to find out what it means without leaving the page
  or reading source code.

## Open questions resolved before implementation

A live-codebase check against this draft surfaced five concrete gaps.
Resolving them here (rather than leaving them implicit) so no sub-step
below starts from an assumption nobody actually confirmed.

1. **§4's "news with its signals" ambiguity.** Unresolved until a human
   confirms it. Default if not explicitly answered before §4 is picked up:
   treat "Recent Judge decisions" as the intended panel and do a
   rename+polish (badge + expandable thesis) rather than building a new
   panel. Building a genuinely separate news/evidence-level view over
   `/screening` (or similar) is explicitly deferred until someone confirms
   that's actually what's wanted — don't build both speculatively.

2. **"Differ meaningfully" threshold (§0, §1).** Fixed at **5 percentage
   points** as the default divergence threshold for both the overview
   strip's "N of M positions differ" count and the diverging-bar-chart's
   delta callouts. Before hardcoding this, check whether the codebase
   already has a comparable constant (e.g. something like
   `MIN_REBALANCE_CONFIDENCE` or a rebalance-trigger threshold in
   Portfolio Construction) — if one exists, reuse it instead of
   introducing a second, potentially-inconsistent number. If none exists,
   5 points is the documented default and should live as a single named
   constant in the dashboard code, not a magic number repeated in two
   places.

3. **§0 health indicator must reuse §3's status categories.** The overview
   strip's traffic-light indicator is defined as: **green/"All systems
   reporting"** only when there are zero rows in §3's "not accessible" or
   "gap" categories — rows in "deferred (paid tier)" never count against
   it. **Yellow/amber** with a single combined plain-language count (e.g.
   "7 sources unavailable," combining §3's own example of 6 "not
   accessible" + 1 "gap") when "not accessible"/"gap" rows exist —
   intentionally one combined number for the overview strip, not two
   separate counts; anyone who wants the "not accessible" vs. "gap" split
   already gets it from §3's own grouped detail table one click down.
   There is no red state distinct from amber for this pass — severity
   beyond "some sources aren't reachable" is out of scope. This must be
   implemented as the same categorization logic §3 uses (shared
   code/lookup), not a second independent classifier that could drift from
   it.

4. **§0 "Total portfolio value" has a real data gap, not just a display
   gap.** The current holdings/allocation responses return quantity and
   allocation (a fraction) per asset, not a USD value or price — only the
   cash line is directly a USD amount. Back-solving a total from
   `cash_quantity / cash_allocation` breaks whenever cash allocation is
   zero or no cash entry exists, which is exactly the kind of fragility
   this doc says to name rather than paper over. Resolution: this is
   grounds for one small, justified backend addition — a `total_value_usd`
   (or per-asset `value_usd`) field computed server-side from
   quantity × current price for every non-cash asset, and directly from
   the stated USD amount (no price lookup, no multiplication) for the
   `CASH` row specifically — added to whichever endpoint Real
   holdings/Portfolio state already read from. This is a genuine, narrow
   exception to "presentation, not content" (§ goal statement) because the
   number literally cannot be derived client-side without it, and it
   should be scoped and reviewed as its own small step before §0 is built,

   not folded silently into the dashboard-only work.

5. **§2's Judge-decision term list corrected.** `expected_alpha` and
   `risk_score` exist on `JudgeDecisionRecord` and are already returned by
   `/judge/decisions/recent`, but the current dashboard only displays
   decision/confidence/thesis — the other fields aren't on screen at all
   yet. Since this is already-real API data, not a new number, surfacing
   `expected_alpha` and `risk_score` in the Recent Judge decisions panel is
   pulled into scope for this pass (as a small, legitimate content
   addition, not a "presentation only" violation) rather than leaving §2's
   plain-language item pointing at fields nobody can see. `regime` is
   corrected here too: it does not currently appear anywhere on the
   dashboard except Calibration summary's `by_regime_note`. The related
   field `regime_at_decision` exists on `DecisionOutcome` (nested inside
   `/portfolio/state`'s response) but `loadPortfolioState()` never renders
   it today — only `outcome_label`, `realized_return`,
   `realized_return_net_of_costs`, and `assumed_fill_method` are shown.
   This is the identical situation as `expected_alpha`/`risk_score` above:
   real, already-returned data that isn't displayed yet. Resolution:
   surfacing `regime_at_decision` in Portfolio state is pulled into scope
   for this pass on the same basis as item 5's other two fields — a small,
   legitimate content addition, not a "presentation only" violation. §2's
   plain-language treatment for "regime" then applies to both locations
   (Calibration summary's existing note and Portfolio state's newly
   surfaced field), not just the one place it happened to already exist.

## Proposed page structure

Group panels under headed sections matching the user's own framing, in
this reading order:

1. **Overview strip** (new, see §0) — a persistent, always-visible summary
   answering the most-asked questions before any scrolling happens.
2. **Your portfolio** — Real holdings, Portfolio state, and the new
   comparison chart(s).
3. **Why** — Recent Judge decisions / news-with-signals (renamed from
   "Judge decisions" if confirmed, see §4).
4. **Track record** — Calibration summary.
5. **System health** — Signal sources, Cost/spend.

This replaces one flat list of six same-weight boxes with a hierarchy that
matches how a non-financial user actually wants to read the page: money
first, reasoning second, trust-building third, plumbing last.

## 0. Overview strip (new)

A single persistent header/banner, visible without scrolling, that answers
the questions this project's own testing sessions kept having to answer
manually:

- Total portfolio value (sum of Real holdings, cash included) and, next to
  it, whether the AI's recommended allocation is close to or far from
  current holdings (e.g. "3 of 5 positions differ from recommendation,"
  using the 5-point divergence threshold fixed in "Open questions
  resolved," item 2). The total-value figure itself depends on a small
  backend addition — see item 4 in that section — and should not be built
  against a back-solved approximation.
- Decision-tracking status in plain language: *"60 decisions logged, 0
  confirmed right or wrong yet — this system is too new to have graded
  itself. Check back later."* This directly defuses the
  "why-is-everything-unresolved" confusion that came up in review, at the
  moment a viewer would otherwise wonder if the page is broken.
- Today's spend vs. daily cap (e.g. "$1.67 of $12.00 today") with a link
  down to the full Cost/spend panel.
- A single traffic-light-style health indicator ("All systems reporting"
  / "N sources unavailable") linking down to Signal sources — not a
  replacement for that panel's honest detail, just an entry point. Uses
  §3's own status categories (see "Open questions resolved," item 3) so a
  deliberate paid-tier deferral never counts as a failure here.

This strip must be built from the same API responses the panels below
already use — no new "summary" endpoint that could drift from the detail
views it's supposedly summarizing, unless the existing endpoints genuinely
can't support it, in which case that's a real backend gap to name
explicitly rather than paper over.

## 1. Portfolio visualization (Real holdings + Portfolio state)

- Replace (or supplement) the two allocation tables with a donut/pie chart
  per panel — one for "what you actually hold" (Real holdings), one for
  "what the system recommends" (Portfolio state) — so the cash-vs-invested
  split and per-asset weight are visually obvious instead of requiring the
  reader to scan a percentage column.
- Build a combined comparison view: a diverging bar chart per asset
  showing "current %" vs. "recommended %" side by side, so the gap
  between holdings and recommendation is visually immediate, not just
  numerically comparable. This is the single highest-value chart on the
  page for the target user, since "what should I actually change" is the
  question the whole system exists to answer.
- Label the delta directly: for each asset where current and recommended
  differ by at least the 5-point threshold (item 2), surface a
  plain-language line — *"You hold 12% in SOL; the system recommends 5% —
  a decrease of 7 points"* — rather than requiring the viewer to subtract
  two numbers themselves.
- Keep the existing tables available (e.g. below the chart, or a toggle) —
  the chart is an addition, not a replacement, per the non-negotiable
  above.
- Cash must remain visually first-class in every chart (its own donut
  slice / bar), matching how it's already treated as a real asset id in
  the data model — don't let "0 tokens, just a dollar amount" cause it to
  get dropped from a chart component built asset-first.

## 2. Plain-language layer, extended beyond Calibration summary

- This session added a "What this means" column to Calibration summary
  only. Extend the same pattern to Portfolio state's Outcome / Mark-to-mid
  / Net of costs / Fill method columns, and to Cost/spend's figures — a
  first-time non-financial viewer currently has no in-page explanation of
  what "net of costs" or "assumed fill method" mean either.
- Extend the same treatment to whatever terms appear in Recent Judge
  decisions (confidence, expected alpha, risk score) and Signal sources
  (paid tier, deferred, N+1 latency) — the plain-language layer should be
  a page-wide convention, not something four of six panels have and two
  don't. `expected_alpha` and `risk_score` are newly surfaced on that
  panel as part of this pass (see "Open questions resolved," item 5) —
  their plain-language treatment ships alongside them, not as a follow-up.
  `regime` gets the same treatment in both places it now appears:
  Calibration summary's existing `by_regime_note`, and Portfolio state's
  newly surfaced `regime_at_decision` (also part of item 5's fix).
- Decide once, project-wide, between two affordances and apply it
  consistently rather than mixing them ad hoc:
  - **Inline description row/column** (this session's existing pattern) —
    always visible, costs vertical space, best for tables read top-to-
    bottom.
  - **Hover/tap tooltip** (`title` attribute or a small `?` icon) — saves
    space, but is undiscoverable on first visit and doesn't work well on
    touch devices without an explicit tap target.
  - Given the target user will likely revisit this page regularly rather
    than read it once, a reasonable default is: tooltips for column
    headers (so the table stays compact once the user is used to it), full
    inline plain-language text for anything that's a *value* rather than a
    *label* (e.g. a specific caveat like "regime-NULL — insufficient
    history"). Worth a quick side-by-side comparison in-browser before
    committing project-wide.
- Add a small glossary link/section (even just an expandable `<details>`
  block) listing every jargon term used anywhere on the page with a one-
  line definition, as a fallback for anything the inline/tooltip layer
  doesn't reach.

## 3. Signal sources panel

- Currently a dense table of ~30 rows, most `NOT_IMPLEMENTED`/
  `UNAVAILABLE` with a paragraph of reasoning each — correct and honest,
  but overwhelming as a first thing a viewer sees.
- Add a summary strip at the top (e.g. "12 sources live, 4 deferred (paid
  tier), 6 not accessible, 1 gap") with the existing detailed table
  collapsed/expandable underneath — the detail must stay one click away,
  not deleted.
- Within the detail table, group rows by status (live / deferred / not
  accessible / gap) instead of leaving them in an arbitrary or
  alphabetical order, so a viewer who does expand it isn't scanning 30
  mixed rows to find the 12 that actually matter day-to-day.
- Distinguish, in the summary strip's language, between statuses that are
  *expected and fine* (e.g. "deferred (paid tier)" — a cost decision, not
  a problem) and statuses that represent a genuine gap — a non-financial
  user shouldn't come away thinking the system is broken because half the
  rows say something other than "live."

## 4. Recent Judge decisions ("news with its signals")

- Per "Open questions resolved," item 1: proceed as a rename+polish of
  this existing panel unless a human has explicitly confirmed a separate
  news/evidence-level view is wanted first. If that confirmation comes
  later, the separate view is a new panel over an existing endpoint
  (`/screening` or similar), not a retrofit of this one.
- Each row's thesis is a dense paragraph; add a short one-line
  summary/badge (decision + confidence, already present) with the full
  thesis expandable, so scanning multiple decisions doesn't require
  reading a paragraph each time.
- If a genuine news/evidence-level panel is built (per the confirmation
  above), design it as "what the AI read" feeding into "what the AI
  decided" — i.e. visually or navigationally link each Judge decision back
  to the underlying signals/evidence rows it was built from, so a curious
  user can trace a recommendation back to its sources instead of taking
  the thesis paragraph on faith.
- Surface confidence, expected alpha, and risk score — the latter two
  newly displayed per item 5 above — as simple visual indicators (e.g. a
  small bar or dot scale) alongside the existing numeric values — a
  "confidence: 0.72" is less immediately legible to a non-financial reader
  than a short filled/empty bar with the number kept alongside it for
  anyone who wants precision.

## 5. Cost / spend

- Give the daily/monthly cap context a simple progress-bar treatment
  (spent vs. cap) rather than requiring the viewer to compare two raw
  numbers.
- Break down spend by the same categories CostGuard already tracks (per
  `COST_TRACKED_TABLES`, per Phase 3 locked decisions) so a curious viewer
  can see *what* is costing money (Judge calls vs. market assessments vs.
  scenario calls), not just the total — this is presentation over data
  that already exists, not a new backend need.
- Apply the plain-language layer here too (§2): a first-time viewer
  benefits from a one-line explanation of why an LLM-driven system has a
  running dollar cost at all.

## 6. Loading/error-state consistency

- Not asked for explicitly, but noticed during this session's live checks:
  saving the API key doesn't automatically retry panels that already
  failed with a 401 before the key was saved — a full page reload is
  currently required. Fix this as part of this pass since it's the same
  kind of "looks broken but isn't" trap the regime-NULL/zero-resolved
  states were designed to avoid.
- Extend the same discipline to any other panel-level fetch failure (not
  just 401s): a panel that fails to load should say so in the same
  plain-language voice as the rest of the page (e.g. "Couldn't reach this
  data — try refreshing" with the raw error available on click/expand for
  anyone who wants it), not a bare stack trace or a silent blank box.
- Add a lightweight "last updated" timestamp per panel (or one page-wide,
  if all panels load together) so a returning user can tell at a glance
  whether they're looking at fresh data — this matters more once the page
  is meant to be revisited regularly rather than opened once to prove the
  API works.

## 7. Accessibility and layout basics (new)

Not in the original draft, but implied by "user-friendly for a
non-financial person," which in practice also means non-technical and
possibly less comfortable with dense UIs generally:

- Responsive layout: the page should be legible on a laptop-width browser
  window without horizontal scrolling of the whole page (individual wide
  tables can scroll internally).
- Sufficient color contrast and don't rely on color alone to convey status
  (e.g. the traffic-light health indicator in §0 needs a text label too,
  not just green/red).
- Consistent typographic hierarchy (section headers per §"Proposed page
  structure" visually distinct from panel titles, visually distinct from
  table headers) so the page reads as organized rather than as six boxes
  glued together.

## Explicitly out of scope for this pass

- No new evidence sources, no Judge/Risk Engine/Portfolio Construction
  changes — this is presentation-only, same boundary Phase 5 itself held.
- No scheduling (still deferred, see `doc/open-work.md`).
- No change to the localhost/API-key access-control model.
- No new "smart" features (alerts, notifications, auto-rebalancing
  suggestions beyond what Portfolio Construction already outputs) — this
  pass makes existing output legible, it doesn't add new analysis.

## Suggested first step, once this prompt is adopted

Same as every prior phase: read this prompt in full, confirm the
non-negotiables and scope boundary explicitly with the user before writing
any code, then pick one area to implement and live-verify before moving to
the next. The five items in "Open questions resolved" above are settled
defaults, not open — proceed against them unless the user overrides one
explicitly. Suggested order, highest-value-first for the stated goal (a
non-financial user opening this page to check their portfolio):

0. **Backend: `total_value_usd`.** Item 4's small backend addition, since
   §0 and §1 both depend on it — do this first so nothing downstream is
   built against a placeholder or a fragile back-solved number.
1. §0 Overview strip — smallest surface area, immediately answers the
   most-asked questions.
2. §1 Portfolio visualization — the core "what should I change" question.
3. §6 Loading/error-state consistency — cheap fix, removes a real
   "looks broken" trap.
4. §2 Plain-language layer (page-wide) and §3 Signal sources summary strip
   — together make the rest of the page legible.
5. §4 Recent Judge decisions and §5 Cost/spend polish.
6. §7 Accessibility/layout basics as a final pass across everything above.
