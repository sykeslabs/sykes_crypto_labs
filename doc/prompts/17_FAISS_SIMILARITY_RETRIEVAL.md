# Add: FAISS historical-similarity retrieval, as an experiment (new todo [HIGH][AI/Quant])

## Context

This is a genuinely new candidate evidence source, not yet in `doc/todo.md` before
this prompt. Read the new todo entry this prompt is paired with first (search
`doc/todo.md` for "Historical-similarity retrieval (FAISS)").

Verified 2026-10-02, read-only:

- The `news` table (`migrations/0002_llm_and_news.sql:5-18`, mirrored by
  `NewsArticle` in `app/news/schemas.py:7-24`) stores `title`, a **nullable**
  `summary` (short text, not full article body), `published_at`, `source`, `url`,
  `sentiment`, `relevant_assets text[]`, and a deterministic `content_hash`
  (`sha256(title|url)`, `app/news/schemas.py:21-23`) — already a stable per-article
  ID, usable directly as the FAISS-vector → article mapping key (or just the
  real `news.id` PK). **Real constraint, not assumable away**: there is no full
  article body anywhere in this system. Step 0 must measure how many rows have a
  non-null, non-trivial `summary` before deciding what to embed.
- No embedding/vector infra exists anywhere in this repo today (confirmed via a
  repo-wide case-insensitive grep for `faiss|embedding|sentence.?transformers|
  vector` across `.py`/`.txt`/`.toml`, excluding `.venv`) — building from zero.
- **The existing no-lookahead mechanism this must reuse, not reinvent**:
  `NewsRepository.get_recent_relevant_news(symbols, since, until, limit_per_asset)`
  (`app/database/repository.py:240-265`) filters `published_at` against an
  `until` bound; `HistoricalReplayService._replay_one_day` threads a `cutoff`
  into `build_assessment_context(..., as_of=cutoff)`
  (`app/benchmarks/replay.py:376-380`), which internally becomes that `until`
  bound (`app/llm/assessment_context.py:42`). Any FAISS retrieval call made
  during backfill/replay must take the same `as_of`/cutoff and only consider
  vectors whose `published_at <= as_of` — no new leakage-prevention logic.
- **Established "does X add value" pattern to follow, not invent**: a `*Record`
  schema + `*Repository.insert()` persisting one row per run (e.g.
  `EvidenceValueReportRecord` / `EvidenceValueReportRepository`,
  `app/benchmarks/schemas.py:105-116` / `app/database/repository.py:1351-1359`),
  driven by a `scripts/run_*.py` entrypoint. Follow this exactly.
- Config convention: `Settings(BaseSettings)` in `app/config/settings.py`, plain
  lower_snake attributes with inline defaults (pydantic-settings' default
  case-insensitive env mapping means `FAISS_ENABLED` → `faiss_enabled`
  automatically, no alias needed) — same style as `news_lookback_hours`/
  `max_news_articles_per_asset` (`app/config/settings.py:73-74`).
- Dependency format: `requirements.txt` is flat `package>=version` lines grouped
  by phase comments.
- **Relation to the existing Deferred "Dedicated web/financial retrieval layer
  (You.com/Tavily/Exa)" item** (`doc/todo.md`, Deferred/gated section): a
  different axis. That item is about fetching *new* external web content; this
  is local semantic search over the project's *own already-ingested* historical
  `news` archive. Not a duplicate — cross-reference, don't merge.

## Two distinct phases — different risk, kept separate on purpose

1. **Retrieval infrastructure** (embeddings + FAISS index + search). Local,
   free (`faiss-cpu` + a small local sentence-transformer), fully modular and
   disableable via `FAISS_ENABLED`. Low-risk, reversible. No LLM cost.
2. **Does it actually help the Judge?** This is NOT free. Measuring whether
   wiring retrieved historical context into the assessment/Judge prompts
   changes and improves decisions requires a **paired backfill replay** (same
   day/asset, with vs. without retrieved context) — real LLM cost, and the
   exact same new-`is_backfilled=true`-row contamination risk already solved
   once for `doc/prompts/07_ADVERSARIAL_INCREMENTAL_VALUE.md`. Do not conflate
   "the retrieval layer works" with "the retrieval layer helps" — those are
   phase 1 and phase 2 respectively, and only phase 2 answers the real question.

## Design (decided — do not change without asking)

- **Module placement**: new `app/retrieval/` for embedding generation + FAISS
  index management + similarity search (keeps it modular/removable, doesn't
  overload `app/news/`). New `app/benchmarks/retrieval_value.py` for the
  phase-2 evaluation harness, matching `evidence_value.py`'s placement exactly.
- **FAISS index holds vectors + a vector-ID → `news.id` mapping only** — never
  duplicate article content inside the index. Index file stored locally on
  disk (path from `FAISS_INDEX_PATH`); the mapping and all real content stay
  in the existing `news` table/`NewsRepository`.
- **Config** (`app/config/settings.py`, own commented block): `faiss_enabled:
  bool = False` (default off — preserves current behavior exactly),
  `faiss_index_path: str = "data/faiss/news.index"`, `faiss_top_k: int = 5`,
  `embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"` (small,
  local, free — flag in Step 0 if a different default is wanted).
- **Dependencies**: add `faiss-cpu>=1.8` and `sentence-transformers>=...` to
  `requirements.txt` under a new `# FAISS similarity retrieval (experimental)`
  comment. `faiss-cpu` only — no GPU variant.

## Step 0 — required, then stop (phase 1)

1. Read-only: count `news` rows with a non-null, non-trivial (e.g. >20 chars)
   `summary`, vs. total rows. Report this before deciding what to embed —
   title-only, title+summary, or title-only-with-a-skip-if-no-summary
   fallback. **Wait for my decision.**
2. Confirm `sentence-transformers/all-MiniLM-L6-v2` (or propose an
   alternative with a stated reason) and get a rough embedding-dimension/
   index-size estimate for the current `news` row count.
3. Confirm the vector-ID↔`news.id` mapping approach (reuse `news.id` directly
   vs. a separate mapping table) and get a one-line OK.

## Implementation — phase 1 (after Step 0)

1. `app/retrieval/embeddings.py`: deterministic, reproducible embedding
   generation from the agreed text field(s). No network calls beyond the
   one-time local model download.
2. `app/retrieval/faiss_index.py`: a small wrapper — build, add, save, load,
   search. Vectors only; mapping lives alongside (e.g. a small JSON/parquet
   sidecar next to the index file, or a new lightweight table — propose the
   simplest option and flag it, don't invent a second database).
3. `app/retrieval/historical_similarity.py`: given a query embedding + an
   `as_of` cutoff, search FAISS, filter results to `published_at <= as_of`
   (reusing the exact mechanism cited in Context — do not re-derive it),
   return top-`faiss_top_k` `(news.id, similarity_score)` pairs, then resolve
   full records via the existing `NewsRepository`.
4. A small CLI/script to (re)build the index from the current `news` table
   (`scripts/build_faiss_index.py` or similar) — must be safely re-runnable
   (idempotent rebuild, not an append-only accumulation of duplicates).
5. **Do not wire this into the live assessment/Judge pipeline in phase 1.**
   `FAISS_ENABLED=False` by default; even when true, phase 1 only adds the
   capability to retrieve, not a change to any prompt or decision path.

## Step 0 — phase 2, required before any replay, then stop

**Reprioritized below 02/03/07, explicitly (2026-10-02, per
`doc/reviews/2026-10-02_INVESTMENT_VALIDITY_REVIEW.md`)**: phase 2 is a
textbook case of adding sophistication before an edge is shown — building
a new retrieval layer is justified in this file only by "does the news
table have enough content to embed," never by evidence that the
*existing* news/LLM pipeline is a binding constraint on performance. **Do
not start phase 2's Step 0 until `02_BASELINE_LADDER.md` and
`03_LLM_ABLATION.md` (revised) have run and shown the existing news/LLM
layer carries signal worth improving.** This is a stronger gate than "07's
contamination solution exists" (the index's prior framing) — it's a
priority gate, not just a mechanics prerequisite. Phase 1 (local, free,
`FAISS_ENABLED=False` by default) is unaffected and remains buildable any
time.

Same shape as `doc/prompts/07_ADVERSARIAL_INCREMENTAL_VALUE.md`'s Step 0 —
reuse that reasoning, don't re-derive it from scratch:

1. Propose a paired design: replay window(s) ending on or before
   `TRAINING_WINDOW_END` (`app/benchmarks/schemas.py`), each day run once with
   and once without retrieved historical context in the assessment/Judge
   prompt. Give days, decisions expected, and LLM cost estimate.
2. **Where do the paired rows go?** Both land as `is_backfilled=true`, so the
   same day counts twice in backfilled stats / the evidence-value pool / B2
   duplicate logic unless tagged and excluded — propose how, same problem
   prompt 07 already solved; reuse that solution if applicable.
3. Noise baseline: non-zero temperature (Judge 0.2, assessments 0.3, no seed)
   means two runs differ even without this change — propose a same-content
   double-run baseline to measure that noise floor.
4. **Wait for my decision and explicit cost approval before any replay.**

## Implementation — phase 2 (after approval)

- Extend the paired-replay mechanism (reuse 07's, if it exists by then) to
  optionally inject retrieved historical context into the assessment/Judge
  prompt, gated by the phase-2 flag, not `FAISS_ENABLED` alone.
- `app/benchmarks/retrieval_value.py` + a `scripts/run_retrieval_value.py`
  entrypoint, following the `evidence_value.py`/`run_evidence_value_
  ranking.py` pattern exactly: compute baseline vs. retrieval-augmented
  directional accuracy, hit rate, Brier score, Sharpe/return delta where
  already computed elsewhere, sample size, and — using a genuine **temporal**
  split, never random — an out-of-sample comparison where the sample allows.
  Persist one row per run via a new `*Record`/`*Repository` pair (or extend
  `evidence_value_reports` if the shape genuinely fits — ask first).
- Retrieval diagnostics, exposed for manual inspection (not a new UI
  requirement — a printed/returned structure is enough): indexed-document
  count, embedding dimension, top-k retrieved `(news.id, score, published_at,
  relevant_assets)` per query, so retrieved relevance can be eyeballed.
- **Success criterion, stated explicitly in the script's own output**: not
  "FAISS runs," but "measurable out-of-sample predictive value beyond the
  existing system." If the result is null, say so plainly — do not add
  complexity chasing an improvement that isn't there (this project's own
  standing methodological principle, `doc/todo.md`'s intro section).

## Tests

Phase 1: embedding generation (deterministic for the same input), index
build/save/load round trip, similarity search (known-nearest-neighbor
sanity check), vector-ID↔`news.id` mapping correctness, empty index (no
crash, empty result), too few documents for a meaningful `top_k`, temporal
filtering (a future-dated article is never returned for an earlier `as_of`).
Phase 2 (after Step 0 approval): paired-row tagging/exclusion from
calibration and evidence-value populations, baseline-vs-augmented comparison
on a small synthetic dataset gives the expected direction.

## Docs (show diff first)

`doc/todo.md` (keep the new item open until phase 2's evaluation has run and
has a real verdict — a null result is a valid, documented close, not a
reason to keep iterating), `doc/history.md`, `doc/decisions.md` (why FAISS,
local-only, the embedding-field decision from Step 0), `doc/scripts.md`.
Document explicitly: why FAISS, what problem it addresses, how the index is
built, how retrieval works, how leakage is prevented, how to run the
experiment, and the baseline-vs-augmented comparison result.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. Reuse
existing abstractions (config, repositories, the `as_of`/`until`
no-lookahead pattern) — don't build a second database or a parallel config
system. `faiss-cpu` only, no paid vector DB. Default behavior
(`FAISS_ENABLED=False`) must preserve current system behavior exactly. Do
not change the live assessment/Judge prompts in phase 1. **No replay or LLM
call in phase 2 without explicit cost approval.** Replays end on or before
`TRAINING_WINDOW_END`. Do not conclude retrieval adds value because it runs
correctly — only a measured, out-of-sample predictive-value result answers
that.
