---

description: Non-negotiable safety, reproducibility, data integrity, and methodological invariants for sykes_crypto_labs
applyTo: "**"
-------------

# Hard Invariants

Violating any of these rules is a bug.

## 1. No lookahead

Every historical query must be bounded by `as_of`/`until`.

Revisable evidence is append-only (`is_revision_of`), never overwritten.

## 2. Cost is always tracked

Any table persisting an LLM result must have an `estimated_cost` column and be registered in `COST_TRACKED_TABLES` (`app/llm/cost.py`).

New LLM calls require a calls/day × $/call estimate against `MAX_DAILY_LLM_COST` before merge.

## 3. Unavailable sources are recorded, never faked

Use `signal_sources` status `UNAVAILABLE` / `NOT_IMPLEMENTED`.

Never approximate unavailable data silently.

## 4. Judge, Risk, and Portfolio remain deterministic and non-agentic

Learned models are diagnostic only and must never be blended into decision logic.

## 5. Holdout integrity

Do not iterate against the embargoed holdout cohort (`HOLDOUT_COHORT_START` in `app/benchmarks/schemas.py`).

Every prompt or logic change followed by a re-run is a new trial and must be recorded.

## 6. Migrations

Migrations are numbered:

`NNNN_description.sql`

They must be idempotent (`if not exists`) and applied in order.

`scripts/apply_migration.py` is currently broken due to authentication. Verify migration state by querying the database, never by relying on its exit code.

## 7. Secrets

Never read or print `.env`.

New keys must use a `SecretStr` field in `app/config/settings.py` and have a blank corresponding entry in `.env.example`.


