---
name: add-signal-source
description: Add or evaluate a new external evidence/data source or LLM stage (API client in app/market_data or app/llm). Covers feasibility check, signal_sources status, settings/env wiring, cost estimate, and tests. Use when the user wants a new data provider, API, or model call.
---

# Add a signal source / LLM stage

## Gate (methodology: tooling earns its place)
- Which **named gap** (evidence-value ranking, reasoning audit, todo item) does this close? If none, say so and ask whether to proceed.
- Prefer official, documented APIs. Note free vs paid tier and rate limits.

## 1. Feasibility, verified for real
- Ask the user before any live API call. Confirm the endpoint, auth, response shape, and history depth (point-in-time availability).
- If not reachable/usable: record `UNAVAILABLE` or `NOT_IMPLEMENTED` in `signal_sources` with the reason, and stop. Never approximate.

## 2. Wiring
- `app/config/settings.py`: optional field, `SecretStr | None = None` for keys (respect `env_ignore_empty`).
- `.env.example`: blank entry with a one-line comment.
- Client in `app/market_data/<source>.py` using `httpx`; pydantic schema for the payload; timestamps as UTC; store observations with their as-of time (no lookahead).
- Missing key → feature records `NOT_IMPLEMENTED`, pipeline still runs.

## 3. Cost
- Data API: rate-limit budget per daily run; paid tier = documented dollar cost (outside CostGuard).
- LLM stage: calls/day × tokens × `PRICING_PER_1K_TOKENS` → $/day vs `MAX_DAILY_LLM_COST`; new table needs `estimated_cost` and a `COST_TRACKED_TABLES` entry; add a `*_PROMPT_VERSION` setting.

## 4. Tests
`tests/test_<source>.py` with mocked HTTP: happy path, missing key, HTTP error, malformed payload.

## 5. Docs
`doc/operations.md` env-var list, `doc/architecture.md` component table, `doc/decisions.md` (why adopted), `doc/history.md` (live findings), `doc/scripts.md` if a script changed.
