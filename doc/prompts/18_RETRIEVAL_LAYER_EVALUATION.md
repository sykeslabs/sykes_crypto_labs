# Evaluate: retrieval-layer alternatives (You.com / Tavily / Exa) vs. RSS+keyword (todo Deferred/gated)

## 0. What this is — and is not

Read `doc/todo.md` → "Deferred / gated" → "Dedicated web/financial retrieval
layer (You.com / Tavily / Exa)" first. **This is an evaluation, not an
integration.** The deliverable is a reproducible offline comparison harness
plus a written report with a go/no-go recommendation — not a change to any
live decision path.

**Out of scope (do not do), same as the todo item's own framing**:
- Wiring any retrieval provider into `app/news/`, `app/judge/context.py`,
  `scripts/run_daily.py`, the scheduler, or any live decision path.
- Changing OpenRouter's role. It remains LLM reasoning/interpretation only —
  no `:online` suffixes, `plugins` web-search params, or browsing tools added
  to `app/llm/openrouter_client.py`, `app/llm/assessment_provider.py`, or
  `app/judge/provider.py`.
- Modifying the existing RSS pipeline (`app/news/rss_client.py`,
  `app/news/relevance.py`, `app/news/service.py`) — it is the baseline under
  test, not something to improve in place.
- New DB tables/migrations. Store evaluation outputs as files (§5) unless
  told otherwise.

## Context — verified 2026-10-02, read-only

- News reaches the Judge via `build_judge_context`
  (`app/judge/context.py:124-130`): `since = as_of - timedelta(hours=
  settings.news_lookback_hours)`, then
  `news_repo.get_recent_relevant_news(symbols=..., since=since, until=as_of,
  limit_per_asset=settings.max_news_articles_per_asset)`, formatted into
  `news_summaries: list[str]` and injected into the prompt
  (`app/judge/context.py:40,220,469-471`). Identical pattern in
  `app/llm/assessment_context.py:60-65,89-100,231-233`.
- `NewsArticle` (`app/news/schemas.py:7-20`): `id, published_at, source,
  title, url, summary, sentiment, relevant_assets`. `content_hash` is a
  computed property (`sha256(title|url)`, line 24), not a stored column.
- **The no-lookahead mechanism any new arm must respect**:
  `NewsRepository.get_recent_relevant_news` (`app/database/repository.py:
  240-265`) filters `.gte("published_at", since).lte("published_at",
  until)` — its own docstring (lines 243-245) states this is the no-
  lookahead bound. Replay threads the same function with `until=cutoff`.
  `EVIDENCE_UNAVAILABLE_FOR_REPLAY` (`app/benchmarks/replay.py:104-119`)
  lists everything replay already treats as non-reconstructable for a past
  date (funding-rate term structure, on-chain valuation/miner metrics,
  stablecoin supply/velocity, `SPOT_ETF_FLOWS`, `PREDICTION_MARKETS`,
  `TOKEN_UNLOCK_SCHEDULE`, applied at `replay.py:462`) — a real,
  already-solved precedent for "what can/can't be honestly reconstructed
  for a historical date," worth reading before designing the point-in-time
  checks in §3.
- **Real news volume today** (queried live): 429 rows, `published_at` range
  2025-12-29 to 2026-09-30 — CoinDesk 173, CoinTelegraph 132, Decrypt 124.
  Re-query this at implementation time; it only grows.
- **The four real `NOT_IMPLEMENTED` categories a retrieval API might
  plausibly help with** — exact current locations, all confirmed, nothing
  guessed: `SPOT_ETF_FLOWS`/`PREDICTION_MARKETS`/`TOKEN_UNLOCK_SCHEDULE`
  (`app/market_data/derivatives_service.py:177-194`), `CUSTODY_OTC_FLOW`
  (`app/market_data/asset_intelligence_service.py:237,257`). (A fifth,
  `SOCIAL_NARRATIVE_SENTIMENT`, also real — `app/market_data/
  macro_service.py:158,191` — but not one a web-search API plausibly
  closes the same way; lower priority to probe.) `doc/todo.md`'s own
  "`NOT_IMPLEMENTED` sources" bullet (Deferred/gated section) is the
  authoritative description of each — read it, don't re-derive the reasons.
- **Optional-API-key convention**: `SecretStr | None = None` settings field
  + an `is_configured` property gating OK vs. NOT_IMPLEMENTED (e.g.
  `glassnode_api_key` at `app/config/settings.py:122`, checked in
  `app/market_data/glassnode.py:27,34`). **Real gap found**: `.env` already
  has `YOU_API_KEY` set, but `app/config/settings.py` has no corresponding
  `you_api_key` field yet — add one following this exact pattern as part of
  §2's inspection/setup, don't invent a different convention.
- `CostGuard` (`app/llm/cost.py:179`, `check()` at `:186`,
  `remaining_budget()` at `:208`) is the existing cost-estimate-then-confirm
  mechanism `scripts/run_replay.py` already uses — reuse it for any LLM
  grading or replay cost in §3's Phase 2, don't build a separate cost gate.
- **Gate status today, checked live**: no real finding yet exists that would
  pass this item's own revisit condition. Evidence-value ranking is still
  n=46 vs. the required 50 (`doc/todo.md`'s evidence-value item); the
  baseline-ladder item is explicitly "not building from zero" but has no
  completed run yet either. **This strongly suggests §1's gate check below
  will conclude "not yet met" — do not be surprised by that, and do not
  treat a "defer" recommendation as a failure to produce something.**

## 1. Gate check first (stop if it fails)

This item is explicitly conditional on `doc/todo.md`'s Section A central
research question having shown **evidence quality is a binding constraint**
on predictive value, not model/weighting/architecture choices.

1. Read Section A of `doc/todo.md` in full, plus the relevant `doc/
   history.md` entries, plus the latest real outputs of `scripts/
   run_evidence_value_ranking.py` and any replay ablations that exist by
   the time this runs.
2. Report in ≤1 page: does current evidence support "evidence quality is
   binding"? Cite exact numbers. Note the standing caveats explicitly —
   the holdout cohort's results are directional-only until
   `holdout_cohort_confirmatory` is true (`EMBARGO_HOLDOUT_COHORT_PROMPT.md`
   work), and news/source-level assessment isn't joinable to resolved
   outcomes today.
3. **If the gate is not met** (the likely outcome per Context above), stop
   and recommend defer, or offer the cheapest possible Phase-1-only probe
   (§3, retrieval quality only, free tiers, no LLM calls) as an option —
   **do not run even that without explicit approval.**

## 2. Inspect before building (short bullets, no rewrites)

- Confirm the real news volume/date range/per-source counts (re-query;
  Context's numbers are a point-in-time snapshot).
- Add the missing `you_api_key: SecretStr | None = None` settings field
  (§Context) if You.com is one of the arms actually built.
- Check each vendor's **current** docs (You.com, Tavily, Exa) for
  endpoints, date filters, rate limits, pricing, ToS before writing a
  client — do not rely on training-data memory of these APIs, they change.
  Record what was checked and when.

## 3. Evaluation design

### Arms

1. **Baseline** — the current RSS+keyword pipeline, using already-persisted
   articles (don't re-fetch; the RSS feeds don't offer history).
2. **You.com** (current leading candidate per the todo item's own framing —
   finance/news-oriented endpoints).
3. **Tavily**.
4. **Exa**.

You.com is the candidate, not the settled choice — the comparison must be
able to recommend any of the four, including "none."

### Fixed historical evaluation set

- Build a frozen query set from real past decision points (a sample of
  `judge_decisions` dates × assets), plus a smaller set targeted at the
  four `NOT_IMPLEMENTED` categories above (e.g. "ETF net flows BTC
  `<date>`", "`<token>` unlock schedule `<date>`").
- Save it as a versioned file with a fixed seed so every arm sees
  identical inputs.
- Keep it small enough to stay within free tiers / an approved budget —
  propose N and the estimated cost, **wait for approval before running
  anything against a real vendor**.

### Point-in-time integrity (critical — this is the hardest real risk here)

Web retrieval APIs search today's index. A naive historical query leaks
future information (later articles, updated pages, retrospective
coverage) — a different, harder version of the same no-lookahead problem
`EVIDENCE_UNAVAILABLE_FOR_REPLAY` already exists to prevent for backfill.

- Use each provider's published-date/end-date filter, set to the decision
  timestamp.
- Independently verify each returned item's publication timestamp; drop
  and count anything after the cutoff or with no verifiable date.
- Report the leakage rate per provider. **A provider that can't be made
  point-in-time safe is ineligible for Phase 2**, regardless of how good
  its raw retrieval quality looks in Phase 1.

### Phase 1 — retrieval quality only (no LLM decisions, no replay)

Per arm, per query, report: relevance (graded 0/1/2 by a fixed rubric —
an LLM grader via the existing OpenRouter client only with explicit cost
approval, with ~10-15% hand-labeled to measure grader agreement either
way); source quality (primary/aggregator/low-quality, duplicate rate);
coverage (% of queries with ≥1 relevant, point-in-time-valid result,
reported separately for the four `NOT_IMPLEMENTED`-category queries);
freshness (lag between event and earliest retrieved coverage); latency,
error rate, cost per query, cost per relevant result.

### Phase 2 — downstream impact (only if Phase 1 shows a clear winner, and only with explicit approval)

- Ablation via the existing replay pipeline: swap the news evidence fed
  to the Judge (baseline vs. best Phase-1 provider), everything else held
  fixed — same paired-replay shape already used for `doc/prompts/
  07_ADVERSARIAL_INCREMENTAL_VALUE.md`; reuse that contamination-tagging
  solution if it exists by then rather than re-deriving it (new rows land
  `is_backfilled=true` here too).
- Use existing metrics only (hit rate, Brier/calibration, the benchmark
  comparison scripts) — don't invent new ones.
- Real LLM calls: print a cost estimate via `CostGuard` and get explicit
  confirmation first, exactly like `run_replay.py` already does.
- State plainly that any result inherits the embargo caveat — directional,
  not confirmatory — and, given the real resolved-outcome sample size
  (check live; order of ~100-300 per Context's recent-session figures),
  report whether any observed difference is distinguishable from noise.

## 4. Implementation constraints

- Isolated location: `app/research/retrieval_eval/` (new top-level
  module — this project has no `app/research/` today; keeping it separate
  from `app/benchmarks/`, which live replay code does import, makes "no
  live path imports this" structurally obvious) + `scripts/
  run_retrieval_eval.py`.
- One thin client per provider behind a minimal common function
  signature — no plugin framework.
- A missing API key → that arm reports `NOT_IMPLEMENTED`, never
  approximated or skipped silently — matches the existing convention cited
  in Context, not a new one.
- Cache raw provider responses to disk so grading/analysis are re-runnable
  without re-paying for vendor calls.
- Tests: date-cutoff filtering (a future-dated/unverifiable-date result is
  dropped and counted), response normalization per provider, missing-key
  behavior. Mock HTTP; no live vendor calls in tests.

## 5. Deliverables

1. Gate-check summary (§1) — including an explicit recommendation if the
   gate isn't met.
2. Inspection notes (§2).
3. Frozen query set + cached raw responses + per-arm metrics (CSV/JSON).
4. A `doc/` report: method, per-arm results table, leakage rates, cost
   projection at production volume (assets × daily runs), which
   `NOT_IMPLEMENTED` categories (if any) a provider could realistically
   close, and a recommendation — **adopt / defer / reject** — with a
   restated revisit condition.
5. A proposed (not applied) `doc/todo.md` diff reflecting the outcome —
   show it, don't apply it without confirmation.

## 6. Questions to ask before starting (don't assume any of these)

- Budget cap for vendor calls and for any LLM grading/replay.
- Which vendor keys exist or should be created (`YOU_API_KEY` is already
  in `.env`; Tavily/Exa are not).
- Query-set size and date range.
- Whether Phase 2 is in scope at all for this round, or Phase 1 only.

## Ground rules

Simplest solution. Don't touch unrelated code — especially not the live
news/judge/assessment path. Flag uncertainty. No vendor API calls, LLM
grading calls, or replay without explicit, itemized cost approval first.
Reuse existing conventions (settings/secrets, `CostGuard`, the `until`
no-lookahead pattern, the B2-style contamination tagging from prompt 07)
— don't invent parallel ones. A "defer" or "reject" conclusion is a valid,
complete deliverable, not an unfinished task.
