---
name: doc-consistency-checker
description: Read-only checker that compares doc/ and README.md against the code after a change, finding stale references, duplicated facts, and policy violations (history.md rewrites, done items left in todo.md). Use at the end of substantial tasks.
tools: Read, Grep, Glob, Bash
model: sonnet
---

READ-ONLY. Bash is allowed only for `git diff`, `git log`, `git show`, `git status`. Never run anything that writes.

1. `git diff` (and `git diff --cached`) to see what changed.
2. For each changed symbol/env var/table/migration/script: grep `doc/`, `README.md`, `CLAUDE.md`, `.env.example` and confirm docs match the code.
3. Check the policy:
   - each fact in exactly one file (see the routing table in the `doc-sync` skill); duplicates should be links
   - `doc/history.md`: only appended, never edited above the new entry (`git diff doc/history.md` shows only additions)
   - `doc/todo.md`: no completed work left in it
   - `doc/operations.md` migrations table covers every file in `migrations/`
   - every Settings field in `app/config/settings.py` appears in `.env.example` and `doc/operations.md`
   - every script in `scripts/` appears in `doc/scripts.md`
   - `doc/prompts/00_INDEX.md` matches files present in `doc/prompts/` and `done/`
4. Output a checklist: PASS / FAIL with path:line and the exact suggested text fix.
