Act as a **senior quantitative researcher, AI/ML researcher, crypto systematic-trading researcher, portfolio/risk specialist, software architect, and extremely skeptical code reviewer**.

You are reviewing the **current state** of the `sykes_crypto_labs` AI crypto portfolio system.

Your primary question is no longer:

> "Is the software technically reliable?"

A substantial reliability and data-integrity review has already been completed and its identified issues have been implemented and validated.

Your primary question is now:

> **Does the underlying investment system have credible evidence of predictive and economic value, or is it primarily a sophisticated decision pipeline that has not yet demonstrated an actual edge?**

Think like someone deciding whether to allocate **CHF 100,000 of their own capital** to this strategy.

Do not reward complexity.

Do not reward AI usage.

Do not reward impressive terminology.

Do not assume a component contributes signal merely because it produces a prediction, score, confidence value, explanation, or sophisticated-looking output.

Your job is to determine what the evidence actually supports.

Follow `CLAUDE.md` throughout: ask, don't assume; simplest solution first; don't touch unrelated code; flag uncertainty explicitly.

---

# 0. IMPORTANT: START FROM THE CURRENT PROJECT STATE

Before reviewing anything:

1. Inspect the repository structure.
2. Read the existing documentation in `doc/`: `architecture.md`, `methodology.md`, `decisions.md`, `history.md`, `operations.md`, `scripts.md`.
3. Read the current TODO: **`doc/todo.md` is the canonical action list** (the dashboard's `#todo-section` is a stale static snapshot — do not treat it as current).
4. Read the implementation-prompt set in **`doc/prompts/`** (see §0.2): `00_INDEX.md` first, then every open numbered prompt (`01_…` through the highest number present), then the list of files in `doc/prompts/done/` (including `PHASE3_LOCKED_DECISIONS.md` and `EMBARGO_HOLDOUT_COHORT_PROMPT.md`).
5. Inspect the current implementation rather than relying on documentation or prompts alone.
6. Inspect the current tests.
7. Inspect the actual persisted data and evaluation outputs available to the project.
8. Understand the complete production pipeline from data ingestion through portfolio construction and evaluation.
9. Identify the current implementation/version of each major component.
10. Establish which previous findings have already been fixed and validated.
11. Run `git status` / `git log` (read-only) and record which relevant work is committed vs. only in the working tree. `00_INDEX.md` states the embargo work (`TRAINING_WINDOW_END`, `HOLDOUT_COHORT_START`, `holdout_cohort_*`, replay guard) was uncommitted at the time it was written — verify the current state; do not assume.

Do **not** assume that the previous review's conclusions are still correct.

Do **not** assume that a prompt's "Context — verified 2026-10-02" claims are still correct.

Verify the current code.

---

# 0.1 PREVIOUSLY CLOSED ISSUES — DO NOT REOPEN WITHOUT EVIDENCE

The following areas have already undergone dedicated forensic review and implementation.

Treat them as **closed unless your current inspection discovers a regression or a new interaction that materially affects them**:

### Risk / portfolio controls

* `MAX_SINGLE_ASSET_ALLOCATION` bypass through WATCH / NO_TRADE.
* A1 cap enforcement.
* A2 interaction between cap corrections and weekly strategy turnover.
* Separation of `strategy` versus `risk_control` turnover.
* Preservation of actual holdings versus target allocation.
* `actual_allocation_before` observability.

### Judge idempotency / duplicate decisions

* Same-day duplicate live Judge decisions.
* B1 same-day duplicate prevention.
* B2 historical duplicate-group exclusion from production calibration.
* Preservation of raw historical duplicate rows for forensic purposes.
* Cost accounting of raw duplicate Judge rows.

### Historical-data integrity

* Historical-series timestamp fallback safety.
* Strict `<= decision_timestamp` historical lookup.
* Historical OHLCV pagination beyond the Binance/API 1,000-row page limitation.
* Held-symbol rescue when assets fall outside the CoinGecko top-65 universe.

### JudgeDecision pagination

* Repository pagination.
* Unlimited retrieval.
* Raw JudgeDecision consumer migration.
* Deterministic ordering.

### DecisionOutcome pagination

* Repository pagination.
* Unlimited retrieval.
* All script consumers migrated.
* Calibration consumers migrated.
* Evidence ranking ordering.
* Reasoning audit retrieval.
* `/calibration/summary` final 2,000-row ceiling.
* `/calibration/outcomes/recent` intentional caller-supplied bounds.

### Completed prompts in `doc/prompts/done/`

* Every `PHASE*_PROMPT.md` and `EMBARGO_HOLDOUT_COHORT_PROMPT.md` is completed work. Do not re-run or rewrite them. Use them as history only (what was decided, when, and why), and to reconstruct researcher degrees of freedom (§19).
* The embargo/holdout-cohort implementation counts as closed **infrastructure** — but per `doc/todo.md` its underlying statistical problem (backfilled and live windows overlap; holdout results directional only) is still open. Keep those two things separate.

The final migration state has been validated with a **704-test suite**, including a meaningful >2,000-row regression test for the final endpoint defect. Re-count the current test suite rather than trusting this number.

Do not spend the review rediscovering these issues.

If you find a regression, interaction, or previously overlooked consequence, document it precisely.

Otherwise treat them as established infrastructure.

---

# 0.2 THE EXISTING EXPERIMENT PROGRAM — `doc/prompts/`

**Every open item in `doc/todo.md` has a matching implementation prompt in `doc/prompts/`**, linked from the item (`**Implementation prompt**: [prompts/NN_….md](…)`) and listed in `doc/prompts/00_INDEX.md` in the same order as `doc/todo.md`. Together those prompts already *are* the project's planned research program. This review must treat them as such.

### Rules

1. **A prompt is a plan, not evidence.** A prompt that has not been run yields no result. If a question in this review depends on an unrun prompt, the answer is **"Evidence unavailable in current project state"** — and you name that prompt as how to obtain it. Do not use a prompt's Context section, or its expected outcome, as evidence.
2. **Critique before you add.** If an existing prompt already specifies an experiment this review would otherwise propose, do not design a parallel one. Evaluate the existing prompt instead and recommend changes to it.
3. **Do not run the prompts.** This review must not execute any prompt's implementation, replays, or LLM calls. Those prompts have their own Step-0 gates, cost approvals and stop-and-wait points.
4. **Respect the index's cross-cutting risks** in every experiment you design or revise. Re-verify them against the code first:
   * new replays add `is_backfilled=true` rows that contaminate the backfilled hit-rate/Sharpe, the evidence-value pool and the reasoning-audit pool, and no tag currently separates experiment rows from the main backfill;
   * replays must end on or before `TRAINING_WINDOW_END`;
   * nothing may be tuned, selected or fitted on decisions with `decision_timestamp >= HOLDOUT_COHORT_START`;
   * every replay inherits item 01's survivorship bias until that is fixed.

### Expected mapping (verify; do not assume)

Use this as a starting map from review sections to existing prompts. Confirm each mapping by reading the prompt, and record any section that **no** prompt covers.

| Review section | Likely existing prompt(s) |
| --- | --- |
| §14 universe integrity / survivorship | `01_PIT_CANDIDATE_UNIVERSE` |
| §8 baselines, Q6, §16 economic validity | `02_BASELINE_LADDER` |
| §7 LLM ablation, Q8 | `03_LLM_ABLATION`, `07_ADVERSARIAL_INCREMENTAL_VALUE` |
| §5 signal decomposition, factor weights | `04_COMPOSITE_WEIGHTS_VALIDATION` |
| §9 information-source ablation | `05_EVIDENCE_VALUE_RANKING`, `03`, `07` |
| §11 calibration | `06_LLM_SELF_REPORTED_CALIBRATION` |
| §17 regime robustness | `08_REGIME_ROBUSTNESS` (gated on 02) |
| §16 sensitivity, §19 degrees of freedom | `09_PARAMETER_SENSITIVITY` (gated on 02) |
| §18 cross-asset generalization | `10_CROSS_ASSET_GENERALIZATION` (gated on 02) |
| §14 temporal integrity, §15 LLM leakage/non-determinism | `11_LLM_LEAKAGE_REVALIDATION` |
| §12–13 portfolio/risk attribution, decision tracing | `12_FORENSIC_EXPLAINABILITY`, `13_STRESS_TEST_REAL_HOLDINGS` |
| §4 news/information advantage, §20 complexity cost | `17_FAISS_SIMILARITY_RETRIEVAL`, `18_RETRIEVAL_LAYER_EVALUATION` |
| Engineering backlog (outside this review's scope unless material) | `14`, `15`, `16` |

Likely gaps to check explicitly: §7 variants **D (simplified single-call LLM)** and **E (news-only LLM)**; §10 dependence-adjusted inference (effective N, block bootstrap, autocorrelation); §13 return attribution (alpha / beta / risk-control / timing); §16 execution-delay and cost-multiplier sensitivity; §19 a count of implicit hypotheses tested; a frozen forward-test protocol (Q7).

### Per-prompt audit (required)

For **every open prompt**, record:

* **Question answered** — which of Q1–Q8 (or none).
* **Still correct?** — do its code/data claims still hold today? List any stale `file:line`, schema or number.
* **Pre-specified success criterion?** — is the pass/fail threshold fixed *before* the data is seen, or left open (which creates researcher degrees of freedom)?
* **Statistical adequacy** — given real N and dependence (§10), can it produce a decisive result, or only noise?
* **Gate / dependency correct?** — is it gated on the right prerequisite? Should it be (un)gated given this review's findings?
* **Contamination handling** — does it handle the cross-cutting risks above?
* **Priority** — expected information value × feasibility, relative to the question "is there an edge?"
* **Complexity check** — does it add sophistication (e.g. 17, 18) before an edge is shown? Apply §30.
* **Verdict** — one of **KEEP / REVISE / MERGE / REPRIORITIZE / RETIRE / ALREADY DONE**, with evidence.

---

# 1. THE CENTRAL QUESTION

Determine whether the system has demonstrated a **real, economically meaningful edge**.

Separate these questions:

### Q1 — Does the system predict anything?

Does it produce predictions that contain information about future outcomes?

### Q2 — Are the predictions calibrated?

Are probabilities/confidence scores meaningful?

### Q3 — Do the predictions rank assets correctly?

Does higher conviction correspond to better future outcomes?

### Q4 — Does the ranking survive portfolio construction?

Can the system convert predictive information into useful positions?

### Q5 — Does the portfolio generate economically meaningful returns?

After transaction costs, slippage, turnover and realistic execution?

### Q6 — Does the edge survive comparison with simple strategies?

This is critical.

### Q7 — Does the edge survive genuinely out-of-sample testing?

This is even more critical.

### Q8 — Is the apparent edge attributable to the AI/LLM components?

Or would a substantially simpler system perform similarly?

Do not conflate these questions.

A strategy can have:

* predictive signal but poor portfolio construction;
* good ranking but no economic alpha;
* high apparent Sharpe caused by overfitting;
* good backtest performance but no genuine out-of-sample evidence;
* useful news information but no need for an LLM;
* useful quantitative signals while the AI components add no measurable value.

Identify which situation actually applies.

For each of Q1–Q8, also state which existing prompt (if any) is designed to answer it, and whether it has been run.

---

# 2. RECONSTRUCT THE COMPLETE DECISION PIPELINE

Trace one complete decision from raw data to portfolio state.

Document the actual sequence:

```text
market / external data
        ↓
universe selection
        ↓
screening
        ↓
feature / indicator generation
        ↓
news / external information
        ↓
LLM research
        ↓
assessment / adversarial analysis
        ↓
Judge
        ↓
Risk Engine
        ↓
correlation / portfolio constraints
        ↓
turnover control
        ↓
portfolio construction
        ↓
execution-cost model
        ↓
outcome evaluation
        ↓
calibration / alpha / performance analysis
```

Do not assume this diagram is correct.

Derive the real pipeline from code.

For every stage identify:

* input;
* output;
* timestamp;
* data availability;
* deterministic versus stochastic behavior;
* model/version;
* parameters;
* persistence;
* downstream consumers;
* potential leakage;
* potential double-counting.

Then answer:

> **Where in this pipeline is the system actually expected to obtain an investment edge?**

If there is no clear answer, identify that as a fundamental problem.

---

# 3. DEFINE THE ACTUAL PREDICTION TARGET

Determine precisely what the system is predicting.

Do not accept vague descriptions such as:

* "market direction";
* "asset quality";
* "future performance";
* "investment opportunity".

Find the actual target mathematically.

For each major prediction/decision determine:

* prediction horizon;
* target variable;
* label definition;
* return definition;
* benchmark;
* threshold;
* treatment of costs;
* treatment of unresolved outcomes;
* treatment of missing prices;
* treatment of delisted/dead assets;
* treatment of stablecoins;
* treatment of cash;
* treatment of HOLD / WATCH / NO_TRADE;
* whether the target is directional, ordinal, continuous, probabilistic, or portfolio-relative.

If different components use different implicit targets, document the mismatch.

Also check whether the open prompts (02, 03, 05, 06, 07 in particular) all evaluate against the **same** target/label. If they use different implicit targets, their results will not be comparable — flag which prompts need aligning.

Then answer:

> **Is the system optimizing one coherent objective or combining several objectives without a clearly defined hierarchy?**

---

# 4. INFORMATION ADVANTAGE

For every major input, ask:

> Why should this information allow the system to predict future crypto returns better than the market?

Classify every information source as:

* **Potentially predictive**
* **Potentially useful but unproven**
* **Likely redundant**
* **Likely noisy**
* **Likely too delayed**
* **Potential leakage risk**
* **No demonstrated value**

Review at minimum:

* OHLCV;
* momentum;
* volatility;
* technical indicators;
* market-cap data;
* universe selection;
* funding;
* open interest;
* liquidations;
* on-chain data;
* macro data;
* sentiment;
* news;
* social signals;
* LLM interpretations;
* external model outputs.

Include each source's real status tag (`OK` / `UNAVAILABLE` / `NOT_IMPLEMENTED`) from the code. A `NOT_IMPLEMENTED` source contributes nothing and cannot have demonstrated value.

Do not merely state that a feature "could be useful."

Ask whether the project has actually demonstrated that it is useful.

Where prompts 17 (FAISS similarity retrieval) and 18 (web/financial retrieval layer) propose to *expand* an information source, state whether this review's evidence supports doing so before the source's current version has demonstrated value.

---

# 5. SIGNAL DECOMPOSITION

Determine what the strategy is actually driven by.

Decompose the final decision into its major information sources.

For example:

```text
quantitative market information
news
LLM research
assessment
adversarial reasoning
Judge
risk constraints
portfolio state
```

Determine whether the final decision is primarily driven by:

* price momentum;
* technical indicators;
* market regime;
* news;
* LLM reasoning;
* historical portfolio state;
* risk constraints;
* heuristics;
* arbitrary thresholds.

Identify where multiple components are effectively expressing the same information.

Explicitly look for:

### Double counting

Example:

```text
price momentum
→ technical score
→ LLM sees momentum
→ Judge sees technical score
→ final score
```

This may look like multiple independent signals while actually being one signal repeatedly transformed.

Identify all such cases.

Check whether prompt 03's layer ladder (factors → + assessments → + adversarial → full Judge) and prompt 05's evidence-value features account for this double counting, or whether they would credit a layer for re-expressing momentum.

---

# 6. AI / ML VALUE AUDIT

For **every AI/ML component**, answer:

1. What exact problem does it solve?
2. What is the baseline?
3. Why should AI outperform that baseline?
4. What empirical evidence currently exists?
5. What sample size supports the conclusion?
6. Is the evaluation genuinely out-of-sample?
7. What would falsify the hypothesis?
8. What is the simplest replacement?
9. Does the component justify its complexity and cost?
10. Which existing prompt tests it, and is that test adequate?

Explicitly inspect:

* classical ML;
* neural networks;
* LLM research;
* LLM sentiment;
* LLM assessment;
* adversarial LLM analysis;
* Judge;
* ensemble logic;
* RAG;
* tool calling;
* multi-agent architecture;
* provider diversity.

For each classify:

**KEEP / MODIFY / QUESTION / REMOVE**

But these classifications must be evidence-based.

---

# 7. LLM ABLATION IS MANDATORY

Treat the LLM architecture as an experimental hypothesis.

Determine whether the project currently has enough data to compare:

### A — Full system

Current production architecture.

### B — No LLM

Remove all LLM-generated information while keeping everything else possible constant.

### C — Quantitative-only

Use deterministic quantitative signals and conventional rules/models.

### D — Simplified LLM

One LLM call with a minimal structured task rather than multiple reasoning stages.

### E — News-only LLM

Test whether the value comes specifically from interpreting unstructured news.

**Start from prompts `03_LLM_ABLATION.md` and `07_ADVERSARIAL_INCREMENTAL_VALUE.md`** (and their dependency on `02_BASELINE_LADDER.md`). For each of A–E, state whether those prompts already cover it, partly cover it, or don't cover it. Design only the uncovered variants, and propose them as **revisions to 03/07** where they share the same harness, or as a new prompt only if they cannot.

Do not implement all experiments automatically.

First determine whether the existing data permits valid experiments.

For each experiment specify:

* population;
* time period;
* training/validation/test split;
* decision horizon;
* target;
* metrics;
* costs;
* statistical test;
* success criterion;
* existing prompt that implements it (or "new prompt required").

---

# 8. BASELINE STRATEGIES

The current system must be compared with simple alternatives.

Determine whether the project currently contains valid comparisons against:

### Market baselines

* BTC buy-and-hold;
* ETH buy-and-hold;
* BTC/ETH benchmark;
* market-cap-weighted crypto portfolio.

### Simple systematic strategies

* buy-and-hold;
* momentum;
* cross-sectional momentum;
* moving-average strategy;
* volatility targeting;
* equal-weight;
* risk-weighted portfolio;
* simple trend following.

### Model baselines

* logistic regression;
* linear regression where appropriate;
* random forest;
* gradient boosting;
* simple factor model.

Do not add every baseline merely for completeness.

Identify the **minimum set of baselines necessary to determine whether the current system adds value**.

Compare that minimum set against the rungs **prompt `02_BASELINE_LADDER.md`** already specifies. Recommend additions or removals of rungs to 02 rather than a separate baseline project. Because 08, 09 and 10 are gated on 02, flag explicitly whether 02 is the single most important unrun experiment in the project.

---

# 9. ABLATION OF INFORMATION SOURCES

Determine whether the project can perform controlled ablations of:

* technical indicators;
* momentum;
* volatility;
* news;
* sentiment;
* on-chain data;
* derivatives data;
* LLM research;
* adversarial analysis;
* Judge;
* individual providers.

For each available ablation, determine whether removing the component changes:

* predictive accuracy;
* Brier score;
* calibration;
* ranking quality;
* realized return;
* alpha;
* Sharpe;
* drawdown;
* turnover;
* transaction costs.

A component that increases complexity but does not improve economically relevant metrics should be questioned or removed.

Map each ablation to the prompt that would perform it (03, 04, 05, 07, or none). Note `05`'s known limitation (per its own context and `scripts/run_evidence_value_ranking.py`): per-source assessment and composite factor score are not joinable to resolved decisions, so it cannot ablate individual evidence sources today. Verify this, and say whether that gap needs its own TODO + prompt.

---

# 10. STATISTICAL VALIDITY

Be extremely skeptical of small samples.

For every important reported result determine:

* N;
* number of independent observations;
* number of assets;
* number of decisions;
* number of resolved outcomes;
* number of BUY/SELL observations;
* number of market regimes;
* confidence interval;
* statistical significance where appropriate;
* multiple-testing exposure;
* dependency between observations.

Distinguish:

```text
number of rows
```

from:

```text
number of independent observations
```

This distinction is essential.

A strategy with 1,000 correlated daily observations does not necessarily have 1,000 independent pieces of evidence.

Explicitly investigate autocorrelation and cross-sectional dependence where relevant.

For every open prompt, estimate whether the realistic N it will run on can detect an effect of economically meaningful size. If not, say so in that prompt's audit (§0.2) — an experiment that can only return noise is low priority until more data accrues.

---

# 11. CALIBRATION

Critically assess:

* Brier score;
* hit rate;
* probability calibration;
* reliability curves;
* confidence distributions;
* directional accuracy.

Determine whether the probabilities actually correspond to observed frequencies.

Ask:

> If the model says 70% probability, does the event actually happen approximately 70% of the time?

Also determine whether calibration is being measured on:

* training data;
* validation data;
* test data;
* production forward data;
* mixed populations.

Do not treat a good Brier score on a tiny or selected sample as convincing evidence.

Check `06_LLM_SELF_REPORTED_CALIBRATION.md` against these requirements, particularly population separation (backfilled / live pre-cohort / holdout cohort).

---

# 12. PORTFOLIO-CONSTRUCTION VALIDITY

Determine whether predictive information survives translation into positions.

Trace examples of:

```text
prediction
→ confidence
→ decision
→ risk adjustment
→ target allocation
→ turnover constraint
→ final allocation
```

Look for situations where:

* a strong signal is neutralized by portfolio constraints;
* a weak signal produces a large position;
* turnover constraints dominate the model;
* correlation adjustments dominate the model;
* cash allocation hides poor predictions;
* risk controls create apparent alpha;
* the final portfolio is mostly a consequence of deterministic rules rather than prediction.

Quantify where possible:

> **How much of observed portfolio behavior is attributable to prediction versus risk/portfolio rules?**

Check whether `12_FORENSIC_EXPLAINABILITY.md` (decision-level tracing) would produce this quantification, or only per-decision explanations. If the latter, specify what is missing.

---

# 13. RISK-CONTROL ATTRIBUTION

This is particularly important because A1/A2 have now been implemented.

Determine separately:

### Strategy-driven movement

Allocation changes caused by investment decisions.

### Risk-control movement

Allocation changes caused by hard portfolio constraints.

Do not attribute risk-control behavior to predictive skill.

Investigate:

* turnover;
* concentration;
* cap corrections;
* correlation controls;
* cash;
* forced reductions;
* execution costs.

Determine how much performance comes from:

1. alpha;
2. beta/market exposure;
3. risk controls;
4. timing;
5. portfolio construction;
6. randomness.

If no existing prompt performs this attribution, propose a TODO + prompt.

---

# 14. BACKTEST / REPLAY METHODOLOGY

Audit the entire evaluation framework.

Verify:

### Temporal integrity

At simulated timestamp T, every input must have existed at or before T.

### Universe integrity

Determine whether the historical universe is realistic.

Look specifically for:

* survivorship bias;
* current top-65 applied historically;
* assets that did not yet exist;
* dead/delisted assets;
* historical market-cap availability;
* universe entry/exit timing.

Assess whether `01_PIT_CANDIDATE_UNIVERSE.md` (the CRITICAL survivorship item) fully fixes this, and whether results of every other prompt should be treated as provisional until it runs.

### Model fitting

Determine exactly where parameters/models are fitted.

Verify separation:

```text
training
→ validation
→ test
→ forward / production
```

Look for hidden tuning on the evaluation period. Verify the actual values and enforcement of `TRAINING_WINDOW_END` and `HOLDOUT_COHORT_START`, and check every open prompt for any step that could fit, select or tune on the holdout cohort.

### Replay determinism

Determine whether replaying the same historical decision produces the same result.

If not, identify all sources of non-determinism:

* LLM responses;
* external APIs;
* market data revisions;
* random seeds;
* provider differences;
* timestamps;
* database state.

Relate this to `11_LLM_LEAKAGE_REVALIDATION.md` (LLM parametric-knowledge leakage during replay): does replay of pre-cutoff dates with current LLMs make LLM-layer replay results fundamentally unreliable?

---

# 15. LLM NON-DETERMINISM

The current system uses external LLM providers.

Determine:

* whether prompts are versioned;
* model versions are recorded;
* provider is recorded;
* temperature/settings are recorded;
* raw responses are persisted;
* research evidence is persisted;
* decisions can be reconstructed;
* provider failures/retries alter results;
* identical historical runs can produce different decisions.

Then distinguish:

### Reproducibility

Can we reconstruct what happened?

from:

### Determinism

Would we get the same answer again?

These are different.

Determine whether the system requires either one for credible research.

(Here "prompts" means the system's **LLM prompts** used in production, not the implementation prompts in `doc/prompts/`. Keep the two separate in the report.)

---

# 16. ECONOMIC VALIDITY

This is the most important section.

Calculate or inspect evidence for:

* gross return;
* net return;
* transaction costs;
* slippage;
* turnover;
* maximum drawdown;
* CAGR;
* Sharpe;
* Sortino;
* Calmar;
* alpha;
* beta;
* exposure;
* hit rate;
* profit factor.

Note `doc/todo.md`'s recorded periodicity correction (old decision-level Sharpe ≈ 1.846 vs. periodicity-corrected pooled-daily ≈ 0.295 vs. BTC buy-and-hold ≈ 0.313). Re-verify these figures and their populations; do not quote them unchecked.

Then ask:

> Would the strategy still look attractive if its estimated edge were reduced substantially?

Perform sensitivity where possible:

* 2× transaction costs;
* 3× transaction costs;
* worse slippage;
* delayed execution;
* one-period execution delay;
* reduced signal strength;
* different thresholds.

Check which of these `09_PARAMETER_SENSITIVITY.md` and `02_BASELINE_LADDER.md` already cover, and propose the missing ones as revisions there.

Do not claim robustness without evidence.

---

# 17. REGIME ROBUSTNESS

Break results into meaningful market regimes.

At minimum investigate:

* bull;
* bear;
* sideways;
* high-volatility;
* low-volatility;
* major crash periods;
* major recovery periods.

Determine whether performance is concentrated in one narrow historical regime.

A strategy that only works in one regime should not be described as generally robust.

Check `08_REGIME_ROBUSTNESS.md` (gated on 02, uses RISK_ON / RISK_OFF / NEUTRAL). Is that regime taxonomy adequate for the regimes listed above? Does the available history actually contain enough of each regime to test?

---

# 18. CROSS-ASSET GENERALIZATION

Determine whether the system works across:

* BTC;
* large caps;
* mid caps;
* small caps;
* different sectors/narratives;
* newly introduced assets;
* assets not used during development.

Look for evidence that the strategy is exploiting a generalizable pattern rather than memorizing specific assets.

If possible, propose:

### Leave-one-asset-out testing

and/or

### Completely unseen asset testing.

Check whether `10_CROSS_ASSET_GENERALIZATION.md` already specifies these; propose them as revisions to it if not.

---

# 19. MULTIPLE TESTING AND RESEARCHER DEGREES OF FREEDOM

Audit the development history and current configuration for evidence of repeated tuning.

Look for:

* repeated threshold changes;
* weighting changes;
* model changes;
* feature selection;
* prompt changes;
* universe changes;
* risk-limit changes;
* evaluation-window changes;
* repeated experiments where only successful versions were retained.

Use `doc/history.md`, `doc/decisions.md`, `doc/prompts/done/` (including `PHASE3_LOCKED_DECISIONS.md`) and `git log` as the primary record.

Ask:

> How many implicit hypotheses have effectively been tested?

A high-performing final configuration after many iterations is not equivalent to a pre-specified hypothesis.

If possible, reconstruct the research degrees of freedom.

Also count the hypotheses the **open** prompts will add if all are run (01–18 and any new ones). Recommend how to control multiple testing across the whole program — e.g. a pre-registered primary experiment, a fixed hypothesis family, or a correction method — and which prompts need a pre-specified success criterion added.

---

# 20. COST OF COMPLEXITY

Estimate the practical cost of the architecture:

* LLM API cost;
* latency;
* operational complexity;
* provider dependency;
* debugging effort;
* reproducibility burden;
* maintenance;
* data dependencies.

Then ask:

> What measurable investment benefit justifies this complexity?

If a simple deterministic strategy could produce similar results, explicitly recommend simplification.

Also estimate the cost of the **open experiment program** itself (the `LLM cost` column in `00_INDEX.md`: which prompts need paid replays, roughly how many replay-days). Recommend the order that yields the most information per franc spent.

---

# 21. FALSE CONFIDENCE AUDIT

Actively identify components that may make the system look more sophisticated than it actually is.

Examples:

* multiple LLM agents;
* adversarial reasoning;
* confidence scores;
* precise probabilities;
* ensemble scores;
* large feature sets;
* complex architecture diagrams;
* high Sharpe;
* large numbers of observations;
* many indicators;
* sophisticated terminology.

For each determine:

1. What does it actually add?
2. What evidence supports that claim?
3. What simpler alternative exists?
4. What experiment would falsify its usefulness?

Apply the same audit to the experiment program: are there prompts that make the project *look* rigorous (many planned analyses) without being able to produce decisive evidence at current N?

---

# 22. FIND THE SIMPLEST SYSTEM THAT COULD WORK

After analyzing the current architecture, design a hypothetical minimal system.

It should contain only components that have demonstrated value.

For example:

```text
clean market data
→ simple predictive features
→ validated model
→ portfolio construction
→ risk controls
→ realistic execution
→ forward evaluation
```

Do not assume this exact architecture is correct.

Derive the minimum architecture from the evidence.

Then compare:

### Current system

versus

### Evidence-based minimal system

Identify every component that the current architecture contains that the minimal system does not require.

---

# 23. REQUIRED EXPERIMENT PROGRAM

Do not merely produce recommendations.

Construct a prioritized research program **as a revision of the existing `doc/prompts/` program**, not a replacement for it.

For every experiment in the program provide:

* hypothesis;
* baseline;
* treatment;
* data;
* period;
* metric;
* statistical method;
* success criterion (fixed in advance);
* expected information value;
* implementation effort;
* LLM cost;
* dependencies / gate;
* **prompt file**: existing (`NN_…`, with verdict KEEP / REVISE / MERGE / REPRIORITIZE) or new.

Prioritize by:

**Expected information value × implementation feasibility**

The highest priority experiments should answer:

> **Does the strategy actually have an edge?**

before experiments that merely make the system more sophisticated.

Output the program as a proposed replacement for the "Suggested order" table in `doc/prompts/00_INDEX.md` (same columns: `#`, `File`, `doc/todo.md section`, `Todo item`, `Depends on`, `LLM cost`), plus a short rationale for every row that moved, was added, merged or retired.

---

# 24. TODO AND PROMPTS — CENTRAL ACTION LIST

`doc/todo.md` is the canonical action list, and **every open TODO item has exactly one implementation prompt in `doc/prompts/`**. Treat the two as one system that must stay in sync.

Before adding anything:

1. Read the complete existing `doc/todo.md`.
2. Understand each existing item **and read its linked prompt**.
3. Identify duplicates (in TODO and among prompts).
4. Identify obsolete items.
5. Identify items whose assumptions have now been disproven.
6. Update existing items (and their prompts) rather than duplicating them.
7. Add only genuinely new findings from this review.

Every actionable finding must be represented in TODO, **and every new or changed open TODO item must have a matching new or updated prompt**.

Use:

* `[CRITICAL]`
* `[HIGH]`
* `[MEDIUM]`
* `[LOW]`
* `[UX]`

Use domain tags where useful:

* `[Quant]`
* `[AI]`
* `[Backtest]`
* `[Data]`
* `[Portfolio]`
* `[Risk]`
* `[Architecture]`
* `[LLM]`
* `[Research]`

Place items in `doc/todo.md`'s existing structure (A. Active research — investment validity: CRITICAL / HIGH / MEDIUM / Confirmed finding; B. Engineering backlog; Deferred / gated with a revisit condition; Declined / Not planned). Read its "Methodological principle" section first and follow it.

Every quantitative TODO should include a validation criterion whenever possible.

Examples:

> **[CRITICAL][Backtest] Establish a genuinely untouched forward-test period and freeze all strategy parameters before evaluation. Success criterion: no parameter, threshold, prompt, feature or universe decision is changed using observations from the frozen evaluation period.**

> **[HIGH][AI] Run a controlled LLM ablation against the deterministic quantitative baseline using identical timestamps, universe, portfolio constraints and execution assumptions. Retain the LLM layer only if it produces statistically and economically meaningful improvement on unseen data.**

> **[HIGH][Quant] Establish confidence intervals for strategy Sharpe and alpha and account for multiple testing and serial/cross-sectional dependence.**

(These examples may already exist in `doc/todo.md` in some form, e.g. the embargo item or prompt 03. Check before adding.)

Do not add TODO items simply because they sound sophisticated.

If the evidence indicates that something should be removed, create a removal TODO (with its own prompt).

If the evidence indicates that a component is useful, do not create unnecessary work around it.

### Prompt-file conventions (match the existing files)

* **Filename**: `doc/prompts/NN_UPPER_SNAKE_CASE.md`, using the next free number (currently 19 onward unless that has changed). Never reuse or renumber an existing number, because `doc/todo.md` links them by filename.
* **Title**: `# Build: …` / `# Analyze: …` / `# Evaluate: …` followed by the todo tag, e.g. `(todo [HIGH][Quant])`, plus `— GATED` where it applies.
* **Sections**, as in the existing prompts:
  * `## Context`: which `doc/todo.md` item to read first; the question; what already exists, as "verified YYYY-MM-DD" claims with `file:line` citations that you actually checked.
  * `## Step 0`: gate check / read-only inspection, with explicit stop conditions and **"Wait for my OK."**
  * `## Implementation` (or Parts / Phases with their own stop points).
  * `## Tests`.
  * `## Docs (show diff first)`.
  * `## Ground rules`: simplest solution, don't touch unrelated code, flag uncertainty, and explicit DB-write and LLM-cost rules.
* Any prompt involving replay must address every cross-cutting risk in §0.2 and route open design choices to a Step-0 "ask the user" gate rather than deciding them silently.
* Any experiment prompt must state its success criterion **before** the data is seen.

### Keeping TODO and prompts in sync

* **New TODO** → new prompt; add the `**Implementation prompt**: [prompts/NN_….md](prompts/NN_….md)` link in the item; add a row to the `00_INDEX.md` table **in the same position as the item appears in `doc/todo.md`**.
* **Modified TODO** → update its prompt (Context claims, gate, dependencies, success criterion) and its index row.
* **Merged TODOs** → one surviving prompt; the absorbed prompt is retired (see below) with a pointer to the survivor.
* **Obsolete / disproven / removed TODO** → do not delete the prompt silently. Move it to `doc/prompts/done/` **only if the work was actually implemented**. Otherwise propose either deletion or a `RETIRED — <reason, date>` header, and **ask me which**.
* **Reprioritized TODO** → move the item in `doc/todo.md` and its row in the index; update the prompt's `Depends on` / gate if it changed.
* **Index** → add a dated entry to `00_INDEX.md`'s "Revision log" describing this review's changes; update its "Cross-cutting risks" section if you found new ones or found any existing one stale.
* Do not edit anything in `doc/prompts/done/`.

After completing the review:

### Re-read TODO and the prompt set.

Verify that every major actionable recommendation is represented, every open TODO item links an existing prompt, every open prompt (other than `00_INDEX.md`) is linked from exactly one TODO item, and the index order matches `doc/todo.md`.

Report:

* TODOs added;
* TODOs modified;
* TODOs removed;
* TODOs explicitly closed as obsolete;
* prompts added (filename);
* prompts revised (filename + what changed);
* prompts merged / retired / moved to `done/`;
* CRITICAL count;
* HIGH count;
* MEDIUM count;
* LOW count;
* top five TODOs (with their prompt files).

---

# 25. EVIDENCE CLASSIFICATION

Every major conclusion must be assigned one of:

### VERIFIED

Directly demonstrated by code, data, tests or reproducible analysis.

### STRONGLY SUPPORTED

Multiple pieces of evidence support the conclusion but some uncertainty remains.

### PLAUSIBLE

Technically/economically reasonable but not yet demonstrated.

### UNVALIDATED

Insufficient evidence currently exists.

### CONTRADICTED

Available evidence argues against the hypothesis.

Do not turn "plausible" into "true".

Do not turn "unvalidated" into "false".

Do not turn a backtest into proof of future performance.

Do not turn a planned experiment (an unrun prompt) into evidence of anything.

---

# 26. IMPORTANT: DO NOT INVENT EVIDENCE

If the project does not contain enough evidence to answer something:

Say exactly:

> **Evidence unavailable in current project state.**

Then specify:

* what evidence is missing;
* why it matters;
* how it should be obtained (name the existing prompt, or the new one you are proposing).

Do not estimate missing results.

Do not fabricate statistical significance.

Do not invent performance numbers.

Do not assume a model works because its architecture is reasonable.

---

# 27. FINAL ASSESSMENT

Do NOT use a 0–100 score.

Numerical scores create false precision and encourage optimization toward arbitrary ratings.

Instead provide an evidence-based status for each dimension:

| Dimension              | Status         | Evidence | Main uncertainty | Resolving prompt(s) |
| ---------------------- | -------------- | -------- | ---------------- | ------------------- |
| Quantitative validity  | VERIFIED / ... | ...      | ...              | ...                 |
| AI/ML validity         | ...            | ...      | ...              | ...                 |
| Data quality           | ...            | ...      | ...              | ...                 |
| Backtesting rigor      | ...            | ...      | ...              | ...                 |
| Portfolio construction | ...            | ...      | ...              | ...                 |
| Risk management        | ...            | ...      | ...              | ...                 |
| Software architecture  | ...            | ...      | ...              | ...                 |
| Practical usefulness   | ...            | ...      | ...              | ...                 |
| Experiment program     | ...            | ...      | ...              | ...                 |

---

# 28. FINAL REPORT STRUCTURE

The final report must contain:

## A. Executive conclusion

Answer:

> **Does the current evidence demonstrate a genuine investment edge?**

Use the evidence classification system.

Do not hedge unnecessarily, but do not claim more than the evidence supports.

---

## B. Current system

Describe what the system actually does today.

Keep this factual and concise.

---

## C. Where the potential edge comes from

Identify the specific mechanisms that could plausibly generate alpha.

For each:

* hypothesis;
* evidence;
* uncertainty;
* the prompt that tests it.

---

## D. What is actually validated

List components whose value is supported by evidence.

---

## E. What remains unvalidated

This section is critical.

List the major claims the project currently makes that are **not yet demonstrated**.

---

## F. Top 10 weaknesses

Rank by **research/investment importance**, not implementation convenience.

For each:

* issue;
* evidence;
* consequence;
* confidence;
* experiment required (prompt file).

---

## G. Components to KEEP / MODIFY / QUESTION / REMOVE

Provide the classification for the major components.

Do not rank components by preference.

Base classification on evidence.

---

## H. Strongest components

Identify what genuinely works well and why.

Include technical infrastructure where it materially supports research validity.

---

## I. Simplification opportunities

Identify components that could be removed without sacrificing demonstrated value.

Prioritize simplification where evidence is absent.

---

## J. Highest-value experiments

Provide the **5–10 experiments that should happen before adding significant new complexity**, each mapped to its prompt file.

Prioritize experiments that can answer whether the system actually works.

---

## K. Recommended research architecture

Describe what the system should evolve toward based on the evidence.

Do not add technology for its own sake.

---

## L. TODO and prompt verification

Report:

* new TODOs;
* modified TODOs;
* removed TODOs;
* obsolete TODOs closed;
* new / revised / merged / retired prompts;
* CRITICAL;
* HIGH;
* MEDIUM;
* LOW;
* five highest-priority TODOs;
* confirmation that `doc/todo.md`, the prompt files and `00_INDEX.md` are consistent (every item ↔ one prompt, same order).

---

## M. Evidence matrix

Create a table:

| Claim | Evidence | Status | What would prove/disprove it | Prompt |
| ----- | -------- | ------ | ---------------------------- | ------ |

Include claims such as:

* the strategy predicts returns;
* LLMs add value;
* news adds value;
* the Judge adds value;
* ensemble logic adds value;
* risk controls improve risk-adjusted returns;
* portfolio construction adds value;
* the strategy beats simple baselines;
* the strategy survives transaction costs;
* the strategy generalizes to unseen periods/assets;
* the strategy is robust across regimes.

---

## N. Per-prompt audit

The table from §0.2 for every open prompt: question answered, still correct, pre-specified success criterion, statistical adequacy, gate, contamination handling, priority, verdict, and required changes.

---

## O. REAL-MONEY DECISION

Answer exactly:

> **Would the current evidence justify allocating CHF 100,000 of real capital to this system today?**

Do not answer based on how impressive the software is.

Base the answer exclusively on the evidence available in the project.

If the evidence is insufficient, specify the exact evidence that is missing, and which prompts, run in which order, would produce it.

---

# 29. OPERATING RULES

Throughout the review:

* Inspect actual code.
* Inspect actual data.
* Inspect actual tests.
* Inspect actual TODOs.
* Inspect the actual prompt files, and verify their claims rather than inheriting them.
* Prefer evidence over architecture diagrams.
* Prefer experiments over opinions.
* Prefer simple baselines over sophisticated assumptions.
* Treat backtests as hypotheses, not proof.
* Treat planned experiments as plans, not evidence.
* Treat LLM reasoning as unvalidated unless empirically demonstrated.
* Separate predictive accuracy from portfolio performance.
* Separate portfolio performance from risk-control effects.
* Separate statistical significance from economic significance.
* Separate reproducibility from determinism.
* Separate historical replay from genuinely out-of-sample forward testing.
* Distinguish independent observations from correlated rows.
* Explicitly account for multiple testing, including across the planned prompt program.
* Do not add complexity merely because it is technically interesting.
* Do not change production behavior merely to make the review easier.
* Do not refactor unrelated code.
* Do not modify the strategy while evaluating it unless the experiment explicitly requires a controlled variant.
* Preserve the current production implementation while establishing the baseline.
* Make experiments reproducible.
* Record exact parameters and populations for experiments.
* Keep documentation, TODO and prompts synchronized with conclusions.

---

# 30. SCOPE CONTROL

This is primarily a **research and investment-validity review**, not a general software cleanup.

Do not spend substantial effort on:

* UI polish;
* cosmetic refactoring;
* naming;
* formatting;
* minor code style;
* non-material architecture improvements.

Only recommend such changes if they materially affect:

* research validity;
* reproducibility;
* investment performance;
* risk;
* maintainability of the research system.

For section-B engineering prompts (`12`–`16`), only audit them as far as they materially affect research validity; otherwise mark them "out of scope — unchanged".

The highest priority is:

> **Prove whether the existing system has an edge before making it more sophisticated.**

Do not optimize the system before determining whether there is anything worth optimizing.

---

# 31. IMPLEMENTATION POLICY

This review is primarily an **assessment and experiment-design exercise**.

Do not automatically implement major strategy changes during the review.

Do not execute any prompt in `doc/prompts/`, run any replay, or make any LLM call.

You MAY make small, non-behavioral changes required to:

* add or update TODO entries in `doc/todo.md`;
* add or revise prompt files in `doc/prompts/` and update `00_INDEX.md`;
* add documentation;
* add read-only audit scripts;
* expose existing data for analysis;
* create isolated experiment infrastructure where clearly necessary.

For every write to `doc/todo.md`, `doc/prompts/` or other `doc/` files: **show the diff first and wait for my OK**, as the existing prompts' "Docs (show diff first)" convention requires. Do not commit.

You MUST NOT silently modify:

* production signals;
* model parameters;
* portfolio rules;
* risk limits;
* evaluation methodology;
* production LLM prompts;
* universe definitions;
* anything in `doc/prompts/done/`;

merely because you believe they should be different.

If a change is recommended, document it as a controlled experiment or TODO, with its prompt.

---

# 32. REQUIRED COMPLETION CHECK

Before finishing:

1. Re-read `doc/todo.md`.
2. Verify every major actionable finding is represented.
3. Verify no duplicate TODOs were created.
4. Verify previously closed infrastructure issues were not unnecessarily reopened.
5. Verify all major conclusions have an evidence classification.
6. Verify all performance claims identify their population and period.
7. Verify no current-vs-historical population is being conflated.
8. Verify no backtest result is presented as proof of future performance.
9. Verify all AI/LLM claims distinguish plausible usefulness from demonstrated usefulness.
10. Verify the strongest conclusions are supported directly by code/data/evaluation evidence.
11. Verify every open TODO item links exactly one existing prompt file, and every open prompt is linked from exactly one TODO item.
12. Verify `00_INDEX.md`'s table order matches `doc/todo.md`, and it has a dated revision-log entry for this review.
13. Verify every new or revised experiment prompt has a pre-specified success criterion, a Step-0 stop gate, and explicit handling of the cross-cutting replay/holdout/survivorship risks.
14. Verify no unrun prompt was cited as evidence.
15. Verify nothing in `doc/prompts/done/` was changed.
16. Report exactly what remains unknown.
17. Report the five highest-value experiments (with prompt files).
18. Report the five highest-priority TODOs (with prompt files).
19. Provide the final real-money evidence assessment.

The standard is not:

> "Does this look like an advanced AI trading system?"

The standard is:

> **"What evidence would convince a skeptical quantitative investor that this system has a repeatable, economically meaningful edge — and does the current project actually provide that evidence?"**
