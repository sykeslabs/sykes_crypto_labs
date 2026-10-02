# Validate: LLM parametric-knowledge leakage mitigation across more events (Confirmed [CRITICAL][AI], not closed)

## Context

Read `doc/todo.md` → "Confirmed [CRITICAL][AI] LLM parametric-knowledge leakage in
backfilled decisions" and `doc/history.md`'s "LLM parametric-knowledge-leakage mitigation,
re-tested against a real crash window" entry first.

Verified 2026-10-02:

- Mitigation: `app/llm/assessment_context.py` and `app/judge/context.py` tell models to
  flag claims not traceable to the run's evidence as unverified priors
  (`ASSESSMENT_PROMPT_VERSION` v2, `JUDGE_PROMPT_VERSION` v3).
- Tested: Aug 2024 XMR (pre-mitigation, leakage drove a SELL); 2022-11-08..10 FTX
  (post-mitigation, $1.84, assessment-level leakage still present, Judge blocked it,
  30/30 WATCH/NO_TRADE).
- Criterion to close: several more distinctive events from **different regimes**,
  unsupported priors consistently detected and never driving a directional call.
- Detection is currently manual review.

## Goal

A repeatable, mostly automated leakage check across ~4–6 historical events.

## Step 0 — required, then stop

1. **Event list.** Propose 4–6 windows (2–3 days each) from different regimes, e.g. a
   sharp crash, a strong rally, a regulatory shock, a quiet period as control. For each:
   dates, why it's distinctive, whether Binance/Coinbase OHLCV reaches that far back for
   the replay assets, which evidence is `EVIDENCE_UNAVAILABLE_FOR_REPLAY`.
2. **Cost**: days × ~$0.575 (no 3f needed unless you argue for it).
3. **Where do these rows go?** They'd become `is_backfilled=true` rows and enter
   backfilled calibration stats, the evidence-value pool and the reasoning-audit pool.
   Ask whether the FTX/XMR test rows are already in those pools, and propose how to tag
   and exclude leakage-test runs (ask before any migration).
4. **Detector design** (propose, don't build yet): for each replayed decision, check
   (a) assessment `raw_response`s for claims flagged as unverified priors, and (b)
   whether a directional (BUY/SELL) Judge decision cites such a claim in `key_evidence`
   or `thesis`. Options: keyword/flag-based (zero cost) vs. one structured LLM check per
   decision, like `app/benchmarks/reasoning_audit.py` (cost per decision). Recommend one.
   Note that a flag-based detector only finds leakage the model admits; say how you'd
   catch unadmitted priors (e.g. event-specific terms that only appear after the date).
5. **Wait for my approval of events, cost, tagging and detector.**

## Implementation (after approval)

- Detector as a small module + script; reuse `reasoning_audit.py` patterns if LLM-based.
- Run replays only as approved; all windows end well before `TRAINING_WINDOW_END`.
- Output per event: assessments with flagged priors (count, %), directional Judge calls
  citing a flagged/unadmitted prior (must be 0 to pass), decision mix.
- Don't change prompts in this task. If an event fails, report it; a prompt change is a
  new version and a separate task.

## Tests

Detector on fixture responses (admitted prior, unadmitted event term, clean); pass/fail
logic per event.

## Docs (show diff first)

`doc/todo.md` (close only if every event passes and you state the limits), `doc/history.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No replay or LLM call
without explicit cost approval.
