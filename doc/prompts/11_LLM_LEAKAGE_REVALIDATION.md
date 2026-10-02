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
4. **Detector design — fix the admitted-leakage rule now, in this prompt,
   not as a Step-0 proposal** (tightened 2026-10-02 per `doc/reviews/
   2026-10-02_INVESTMENT_VALIDITY_REVIEW.md`: leaving the exact rule to be
   "proposed then approved" still leaves real researcher degrees of
   freedom in what counts as "flagged"). The rule: for each replayed
   decision, a directional (BUY/SELL) Judge decision **fails** if its
   `key_evidence` or `thesis` cites a claim that the same decision's own
   assessment `raw_response`s flagged as an unverified/unsupported prior
   (exact keyword match against the phrasing this project's own prompts
   already instruct models to use for this — e.g. "unverified prior,"
   "not traceable to," "no evidence was found to substantiate" — confirm
   the exact current phrasing in `app/llm/assessment_context.py`/
   `app/judge/context.py` before finalizing the match list, don't guess
   from memory). Zero LLM cost, keyword-based — still propose an
   LLM-based alternative in Step 0 only if the keyword approach proves too
   brittle on real fixture data, not as a default.
   **Explicitly, permanently out of scope for this detector**: unadmitted
   leakage (an event-specific term/narrative the model states as
   established fact, with no hedging language at all). Report the
   detector's result ONLY as "no admitted-leakage-driven directional call
   found in these N events," never as "leakage risk is resolved" — state
   this distinction in the prompt's own final-report template (see Docs
   below), not left to the implementer's judgment at write-up time. If
   events still reveal event-specific terms the model states as fact with
   no hedging, flag those separately as "possible unadmitted leakage, not
   caught by this detector" — do not silently pass them.
5. **Wait for my approval of events, cost, and tagging** (the detector
   rule itself no longer needs separate approval, per point 4 above —
   only the event list, cost, and row-tagging approach remain open).

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

`doc/todo.md` (close only if every event passes and you state the limits —
and the limits **must** include the unadmitted-leakage blind spot from
point 4 explicitly, every time, not only when something was caught),
`doc/history.md`.

## Ground rules

Simplest solution. Don't touch unrelated code. Flag uncertainty. No replay or LLM call
without explicit cost approval.
