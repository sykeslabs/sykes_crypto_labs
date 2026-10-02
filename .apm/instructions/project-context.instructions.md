---

description: Project purpose, technology stack, operational boundaries, commands, and core principles for sykes_crypto_labs
applyTo: "**"
-------------

# Project Context

## What this is

sykes_crypto_labs is an auditable AI crypto research and advisory system.

**PAPER TRADING ONLY.**

The system does not execute real trades.

Current technology includes:

* Python 3.12
* Supabase / PostgreSQL
* pydantic-settings
* httpx
* FastAPI dashboard (localhost only)
* LLMs via OpenRouter

Phases 1–5 are complete.

Phase 6 (exchange/testnet execution) is deliberately on hold.

### Trading boundary

Never add:

* order placement
* exchange authentication
* private trading endpoints
* real-money execution

## Core principles

* Empirical evidence takes priority over architectural sophistication.
* Do not claim model improvements without measurable evaluation evidence.
* Preserve reproducibility of experiments and data pipelines.
* Separate data collection, feature engineering, prediction, evaluation, and reporting.
* Validate data quality before drawing conclusions from model results.

## Commands

Commands are executed from the repository root on Windows.

### Activate environment

```text
.venv\Scripts\activate
```

### Run tests

```text
python -m pytest -q
```

Tests must pass without live credentials.

### Run a specific test

```text
python -m pytest tests/test_judge.py -q
```

### Run collector

```text
python -m app.main
```

This writes to live Supabase.

Ask before running it.

### Run full daily pipeline

```text
python -m scripts.run_daily
```

This incurs real LLM costs.

Ask before running it.

### API/dashboard

Consult `doc/operations.md` for API and dashboard operations.
