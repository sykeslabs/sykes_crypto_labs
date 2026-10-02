# CLAUDE.md — crypto-ai-portfolio

## Working rules (non-negotiable)

Ask, don't assume. If something is unclear, ask before writing a single line. Never make silent assumptions about intent, architecture, or requirements.

Simplest solution first. Always implement the simplest thing that could work. Do not add abstractions or flexibility that weren't explicitly requested.

Don't touch unrelated code. If a file or function is not directly part of the current task, do not modify it, even if you think it could be improved.

Flag uncertainty explicitly. If you are not confident about an approach or technical detail, say so before proceeding. Confidence without certainty causes more damage than admitting a gap.

## What this is

Auditable AI crypto research/advisory system. **PAPER TRADING ONLY.** Python 3.12, Supabase (Postgres), pydantic-settings, httpx, FastAPI dashboard (localhost only), LLMs via OpenRouter. Phases 1–5 done; Phase 6 (exchange/testnet execution) is **on hold by deliberate choice**. Never add order placement, exchange auth, or private trading endpoints.

## Commands (Windows, from repo root)

- Activate: `.venv\Scripts\activate`
- Tests (must pass with NO live credentials): `python -m pytest -q`
- One test file: `python -m pytest tests/test_judge.py -q`
- Collector only: `python -m app.main`  ← writes to live Supabase
- Full daily pipeline: `python -m scripts.run_daily`  ← **real LLM cost**, ask first
- API/dashboard: see `doc/operations.md`

## Hard invariants (violating any of these is a bug)

1. **No lookahead.** Every historical query is bounded by `as_of`/`until`. Revisable evidence is append-only (`is_revision_of`), never overwritten.
2. **Cost is always tracked.** Any table persisting an LLM result has an `estimated_cost` column AND is registered in `COST_TRACKED_TABLES` (`app/llm/cost.py`). New LLM calls need a calls/day × $/call estimate against `MAX_DAILY_LLM_COST` before merge.
3. **Unavailable sources are recorded, never faked.** Use `signal_sources` status `UNAVAILABLE` / `NOT_IMPLEMENTED`; never approximate silently.
4. **Judge / Risk / Portfolio stay deterministic and non-agentic.** Learned models are diagnostic only, never blended into decisions.
5. **Holdout integrity.** Don't iterate against the embargoed holdout cohort (`HOLDOUT_COHORT_START` in `app/benchmarks/schemas.py`). Every prompt/logic change + re-run is a "trial"; record it.
6. **Migrations** are numbered `NNNN_description.sql`, idempotent (`if not exists`), applied in order. `scripts/apply_migration.py` is currently broken (auth); verify by querying, never by its exit code.
7. **Secrets**: never read or print `.env`. New keys → `SecretStr` field in `app/config/settings.py` + blank entry in `.env.example`.

## Code conventions

- Config only via `get_settings()`; optional settings default to `None` and gate their feature.
- Pydantic models for every external/LLM payload; validate, don't trust.
- Tests mock HTTP and Supabase (`pytest-mock`); no network in tests.
- Comments explain *why* (real incidents, dates), matching existing style.

## Documentation policy (a task isn't done until docs are)

Flow: Understand → Implement → Test → Update docs → Verify consistency. Each fact lives in exactly ONE place:

| File | Truth about |
|---|---|
| code | implementation |
| `doc/architecture.md` | current architecture |
| `doc/methodology.md` | process |
| `doc/decisions.md` | rationale (dated; observed fact ≠ inferred reason) |
| `doc/history.md` | what happened — **append-only, never rewrite** |
| `doc/todo.md` | what's open (no "done" content) |
| `doc/operations.md` | setup, env vars, migrations table, run sequence |
| `doc/scripts.md` | every script, cost, schedule |

Implementation prompts live in `doc/prompts/NN_*.md` (index: `00_INDEX.md`); completed ones move to `doc/prompts/done/`.

## Skills & agents available

Skills: `/run-implementation-prompt`, `/write-implementation-prompt`, `/new-migration`, `/add-signal-source`, `/doc-sync`.
Agents: `prompt-verifier`, `validity-reviewer`, `doc-consistency-checker` (all read-only).
