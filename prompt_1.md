# AI Crypto Portfolio System — Claude Code Master Prompt

You are building a modular AI-driven cryptocurrency portfolio management system in Python.

The goal is to create a robust, auditable research and portfolio-management system inspired by multi-model AI investing approaches such as "The Claude Portfolio", but focused on crypto assets.

The system must initially operate **100% in paper-trading mode**. No real-money trading, no exchange credentials, and no live orders are allowed in the initial implementation.

---

## 1. Core objectives

Build a system that can:

1. Collect cryptocurrency market data.
2. Collect relevant crypto news and market context.
3. Send the same research context to multiple LLMs.
4. Obtain structured investment assessments from:

   * Claude
   * OpenAI
   * Gemini
5. Have a separate AI "Judge" critically evaluate the model opinions.
6. Produce a portfolio recommendation.
7. Apply deterministic risk rules before any portfolio change.
8. Execute simulated trades.
9. Track portfolio performance.
10. Compare the AI portfolio against benchmarks.
11. Store all decisions and inputs so that every decision can be audited later.
12. Eventually support real exchange execution without redesigning the architecture.

The system should be designed so that the AI recommends actions, but **the Risk Engine always has the final authority over whether an action is permitted**.

---

# 2. Technology stack

Use:

* Python 3.12+
* PostgreSQL via Supabase
* Supabase Free plan initially
* Pydantic
* httpx
* python-dotenv
* pytest
* Decimal for financial calculations
* UTC timestamps everywhere
* OpenRouter for LLM access initially
* CoinGecko API for initial market data
* REST APIs
* Git

Do NOT introduce unnecessary frameworks.

Do NOT build a microservice architecture.

Use a **modular monolith** initially.

The architecture should remain easy to split into services later if necessary.

---

# 3. Cost constraint — VERY IMPORTANT

The system must be designed to operate comfortably within the following initial cost target:

* Supabase: Free plan
* CoinGecko: Free/Demo API
* OpenRouter: pay-as-you-go with strict token/cost control
* Python application: local execution initially
* No paid infrastructure unless explicitly requested

Optimize the system for low usage.

Do NOT continuously write large amounts of redundant market data into Supabase.

Do NOT store raw API responses unnecessarily.

Prefer:

* periodic snapshots
* normalized data
* deduplication
* compact JSON
* retention policies
* aggregated historical data

The expected initial system is small and should comfortably fit within Supabase Free limits.

The architecture must make it possible to move to Supabase Pro later without redesigning the application.

---

# 4. Supabase requirements

Use Supabase PostgreSQL as the persistent database.

The backend may use the Supabase service-role key.

IMPORTANT:

* Never expose SUPABASE_SERVICE_ROLE_KEY to frontend code.
* Never commit credentials.
* Never put credentials directly into source code.
* Use `.env`.
* Provide `.env.example`.
* Add `.env` to `.gitignore`.

The application should use environment variables such as:

SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=

COINGECKO_API_KEY=

OPENROUTER_API_KEY=

Do not require all credentials during Phase 1.

---

# 5. Initial cryptocurrency universe

Start with:

* BTC
* ETH
* SOL
* XRP
* BNB
* HYPE

Make the asset universe configurable through the database/configuration.

Do NOT hard-code the asset universe throughout the application.

Eventually the system should be able to support additional assets without code changes.

---

# 6. Architecture

Use the following logical components:

market_data/
news/
llm/
judge/
portfolio/
risk/
trading/
benchmarks/
database/
config/
tests/

Suggested structure:

crypto_ai_portfolio/
│
├── app/
│   ├── config/
│   ├── database/
│   ├── market_data/
│   ├── news/
│   ├── llm/
│   ├── judge/
│   ├── portfolio/
│   ├── risk/
│   ├── trading/
│   ├── benchmarks/
│   └── main.py
│
├── tests/
│
├── migrations/
│
├── scripts/
│
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── pyproject.toml

You may improve this structure if there is a strong technical reason.

Do not over-engineer it.

---

# 7. Database design

Create normalized PostgreSQL tables.

At minimum:

## assets

* id
* symbol
* name
* active
* created_at

## market_snapshots

* id
* asset_id
* timestamp
* price
* market_cap
* volume_24h
* price_change_24h
* price_change_7d
* price_change_30d
* source

Add appropriate indexes.

Avoid duplicate snapshots.

## news

* id
* published_at
* source
* title
* url
* summary
* sentiment
* relevant_assets
* content_hash
* created_at

Use content_hash to prevent duplicates.

## llm_analyses

Store:

* id
* run_id
* asset_id
* provider
* model
* prompt_version
* timestamp
* input_hash
* response
* action
* confidence
* target_allocation
* investment_horizon
* bull_case
* bear_case
* catalysts
* risks
* invalidation_conditions
* token_usage
* estimated_cost

## judge_decisions

Store:

* id
* run_id
* asset_id
* timestamp
* prompt_version
* decision
* confidence
* reasoning
* model_agreement
* key_disagreements
* rejected_arguments
* final_recommendation

## portfolio_snapshots

Store:

* timestamp
* total_value
* cash
* invested_value
* daily_return
* cumulative_return
* drawdown

## positions

Store:

* asset
* quantity
* average_entry_price
* current_price
* market_value
* allocation
* unrealized_pnl

## trades

Store:

* timestamp
* asset
* side
* quantity
* price
* fees
* slippage
* reason
* decision_id
* simulated/live status

Initially all trades must be simulated.

## benchmarks

Track:

* BTC buy-and-hold
* ETH buy-and-hold
* equal-weight crypto portfolio

Eventually:

* S&P 500
* Nasdaq 100

---

# 8. Auditability

This is a critical requirement.

Every AI decision must be reproducible/auditable.

Store:

* timestamp
* market data used
* news context used
* provider
* model
* prompt version
* structured model response
* judge response
* risk decision
* resulting portfolio action
* simulated trade
* later performance

Never allow future information to enter historical decisions.

For example:

A decision generated on September 3 must never use news published on September 4.

Use timestamps and publication times to enforce this.

---

# 9. LLM architecture

Initially use OpenRouter as the unified LLM gateway.

Create an abstraction such as:

LLMProvider

with implementations/configuration for:

* Claude
* OpenAI
* Gemini

The rest of the application must NOT depend directly on OpenRouter-specific implementation details.

This makes it possible to later connect directly to Anthropic/OpenAI/Google for benchmarking.

Do not use free models for the core production-quality portfolio decision unless explicitly configured.

Models must be configurable through environment variables/configuration.

Example:

CLAUDE_MODEL=
OPENAI_MODEL=
GEMINI_MODEL=
JUDGE_MODEL=

---

# 10. Structured LLM output

LLMs must return structured data.

Use Pydantic models.

Example conceptual schema:

InvestmentAnalysis:

* asset
* action: BUY | HOLD | SELL
* confidence: 0.0–1.0
* target_allocation
* horizon
* thesis
* bull_case
* bear_case
* catalysts
* risks
* invalidation_conditions

Do NOT rely on parsing arbitrary natural-language responses.

If an LLM produces invalid structured output:

1. validate it
2. optionally retry once
3. log the failure
4. never silently accept malformed output

---

# 11. Research process

For each portfolio run:

1. Retrieve current market data.
2. Retrieve relevant recent news.
3. Build a research context.
4. Send the SAME factual context to all models.
5. Obtain independent analyses.
6. Send the analyses to the Judge.
7. Judge evaluates arguments critically.
8. Portfolio Manager creates target allocations.
9. Risk Engine validates the proposed changes.
10. Paper Trading Engine executes permitted trades.
11. Store everything.

The models should not simply vote.

The Judge must explicitly identify:

* strongest argument
* weakest argument
* disagreements
* unsupported assumptions
* missing information
* potential confirmation bias
* conflicts between technical and fundamental signals

---

# 12. Portfolio Manager

The Portfolio Manager converts the research/Judge output into target allocations.

Initial constraints:

* cash is allowed
* max 40% allocation to a single asset
* no leverage
* no short positions
* no derivatives
* no borrowing
* no forced full investment

The Portfolio Manager must produce:

* current allocation
* target allocation
* proposed trades
* rationale

The Portfolio Manager does NOT bypass the Risk Engine.

---

# 13. Risk Engine

The Risk Engine is deterministic.

AI cannot override it.

Initial rules:

* max 40% single-asset allocation
* max 5% portfolio allocation increase per trade
* no leverage
* no short selling
* only approved assets
* reject stale market data
* reject missing market data
* reject invalid prices
* reject invalid quantities
* configurable maximum daily loss
* configurable maximum total portfolio drawdown
* configurable maximum trade value

All risk decisions must be logged.

Example:

RiskDecision:

* approved
* rejected
* reasons
* violated_rules

---

# 14. Paper Trading

Initial portfolio:

$10,000 virtual capital.

Starting state:

cash = $10,000
positions = 0

Simulate:

* trading fees
* bid/ask spread or slippage
* execution price
* timestamps

Never assume perfect execution.

Every simulated trade must be stored.

---

# 15. Benchmarks

The system must automatically compare the AI portfolio with:

1. BTC buy-and-hold
2. ETH buy-and-hold
3. Equal-weight portfolio

Calculate:

* total return
* daily return
* annualized volatility
* maximum drawdown
* Sharpe ratio
* number of trades
* fees
* win rate
* performance relative to BTC
* performance relative to ETH

Do not optimize the AI portfolio against historical data initially.

Avoid look-ahead bias.

---

# 16. Scheduling

Initially:

NO automatic scheduler.

The system should be manually executable.

Example:

python -m app.main

Later implement:

* daily run
* 4-hour run
* scheduled research
* monitoring

Scheduling should be added only after the core pipeline works.

---

# 17. Error handling

The system must gracefully handle:

* CoinGecko API failure
* OpenRouter failure
* individual LLM failure
* malformed LLM response
* database failure
* stale data
* missing news
* rate limits
* timeouts

One failed LLM should not necessarily stop the entire research run.

However:

If insufficient reliable information is available, the system should default to:

HOLD

rather than inventing information.

---

# 18. Logging

Use structured logging.

Every pipeline run gets a unique:

run_id

Example:

RUN-2026-09-03-001

All downstream records should reference this run.

Log:

* start/end
* API calls
* errors
* LLM calls
* token usage
* costs
* decisions
* risk results
* trades

---

# 19. Cost monitoring

Track LLM token usage.

For every LLM call record:

* input tokens
* output tokens
* estimated cost
* model

Implement a simple daily/monthly cost summary.

The system should make it easy to answer:

"How much did the AI portfolio system cost this month?"

Add configurable limits:

MAX_DAILY_LLM_COST=
MAX_MONTHLY_LLM_COST=

If the limit is reached:

* do not make further LLM calls
* log the reason
* fail safely

---

# 20. Security

Never:

* commit `.env`
* expose API keys
* store secrets in database unnecessarily
* put exchange withdrawal permissions into API keys
* store private keys in the repository

When exchange integration is eventually implemented:

* API key must have trading permissions only
* withdrawal permissions must remain disabled
* use sandbox/testnet first
* live trading must require explicit configuration

There must be a hard separation between:

PAPER

and

LIVE

execution modes.

Default:

PAPER

---

# 21. Testing

Write tests for:

* Pydantic schemas
* market data normalization
* duplicate detection
* risk limits
* allocation calculations
* portfolio accounting
* trade execution
* benchmark calculations
* stale-data rejection
* invalid-data rejection
* cost-limit enforcement

Financial calculations should use Decimal rather than float where appropriate.

---

# 22. Development methodology — VERY IMPORTANT

Do NOT implement the entire system in one step.

Work in phases.

After each phase:

1. Run tests.
2. Run the application.
3. Check database state.
4. Show what was created.
5. Explain how I can verify it.
6. STOP and wait for my confirmation.

Do not continue automatically to the next phase.

---

# PHASE 1 — Foundation

Implement ONLY:

* project structure
* Python environment configuration
* `.env.example`
* `.gitignore`
* configuration management
* Supabase database connection
* database migrations/schema
* asset table
* market_snapshots table
* CoinGecko integration
* retrieval of current prices for the configured assets
* normalized market snapshot
* persistence into Supabase
* basic logging
* tests

Do NOT implement:

* LLMs
* OpenRouter
* portfolio decisions
* trading
* exchange integration
* scheduler

At the end of Phase 1, I must be able to run:

python -m app.main

and see a successful market-data collection.

---

# PHASE 2 — Multi-model AI

Only after I approve Phase 1:

Implement:

* OpenRouter integration
* Claude
* OpenAI
* Gemini
* Pydantic structured outputs
* prompt versioning
* LLM logging
* token/cost tracking
* failure handling

Do not implement trading yet.

---

# PHASE 3 — Judge + Portfolio + Risk

After approval:

Implement:

* Judge
* Portfolio Manager
* Risk Engine
* target allocation calculation
* risk decision logging

Still paper only.

---

# PHASE 4 — Paper Trading

After approval:

Implement:

* virtual portfolio
* simulated execution
* fees
* slippage
* positions
* trades
* portfolio snapshots
* benchmark tracking
* performance metrics

---

# PHASE 5 — Dashboard + Automation

After approval:

Implement:

* dashboard
* portfolio overview
* AI opinions
* Judge decisions
* trades
* performance
* benchmark comparison
* cost monitoring
* scheduled execution

---

# PHASE 6 — Exchange Integration

Only after the paper-trading system has been tested sufficiently:

Design exchange integration.

Initially:

TESTNET / SANDBOX ONLY.

Do not activate live trading.

Live trading requires explicit configuration and a separate safety review.

---

# 23. Important implementation principle

The system is an experiment in AI-assisted portfolio management.

Do not assume that:

* AI predictions are correct
* model consensus is predictive
* past performance guarantees future performance
* more LLMs automatically produce better decisions

The architecture must allow us to evaluate whether the AI system actually adds value.

The benchmark comparison is therefore as important as the AI portfolio itself.

---

# 24. First task

Before writing code:

1. Inspect the existing project directory.
2. Determine whether a Python project already exists.
3. Determine whether Git is already configured.
4. Determine whether there is an existing Supabase configuration.
5. Do NOT overwrite existing work.
6. Report what you found.
7. Propose the exact Phase 1 implementation plan.
8. Only then implement Phase 1.

Do not ask me for API secrets in chat.

If credentials are required, tell me exactly which environment variable I need to populate locally.

Start by inspecting the project.
