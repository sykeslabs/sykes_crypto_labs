---
name: run-implementation-prompt
description: Execute one of the numbered implementation prompts in doc/prompts/ (e.g. "run prompt 05", "implement 13_STRESS_TEST_REAL_HOLDINGS") end to end, including its gate check, tests, docs, and moving it to done/.
argument-hint: <NN or filename>
disable-model-invocation: true
---

# Run an implementation prompt

Target: `doc/prompts/$ARGUMENTS*` (resolve the NN prefix to exactly one file; if 0 or >1 match, stop and ask).

## 1. Pre-flight (stop and report if any fail)
- Read the whole prompt, plus its row in `doc/prompts/00_INDEX.md` and its linked item in `doc/todo.md`.
- Check its **Depends on** column: every dependency must already be in `doc/prompts/done/`.
- `git status --porcelain`: if there are uncommitted changes the prompt builds on, tell the user to commit first.
- Run the prompt's own **Step 0 / gate check**. If it says "defer" or needs user confirmation (e.g. `14_HOLDINGS_CORRECTION`), stop and ask.
- If the prompt has **LLM cost**, state the estimate and get an explicit OK before any live run.

## 2. Re-verify, don't trust
The prompt's Context section cites file:line. Spot-check every citation you rely on; code may have moved. If a claim is now wrong, stop and report it. Don't quietly adapt.

## 3. Implement
- Only the scope the prompt names. "Out of scope" lists are binding.
- New migration? Use `/new-migration`. New source? Use `/add-signal-source`.
- Tests first or alongside; no network in tests.

## 4. Validate
- `python -m pytest -q` must pass.
- Live verification steps from the prompt: run only after the user OKs them (they hit Supabase / cost money).

## 5. Docs and close-out
- Run `/doc-sync` for the change.
- Append a dated entry to `doc/history.md` (append only) with real observed numbers.
- Remove or reduce the item in `doc/todo.md`. Don't leave "done" text there.
- Move the prompt to `doc/prompts/done/` and update `00_INDEX.md` (table + revision log line).
- Finish by delegating to the `doc-consistency-checker` agent and report its findings.

Do not commit. Summarise the diff and let the user commit.
