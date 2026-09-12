"""Runs the full recommended daily sequence in one command -- see
doc/operations.md's "Recommended daily sequence" for why these are
separate invocations (not one combined `python -m app.main ...`) and in
this exact order:

1. `python -m app.main --with-llm`
   Run alone, first. Its own news+LLM-research code runs LAST inside
   app/main.py, so combining it with --with-judge in one invocation would
   mean the Judge only ever sees YESTERDAY's stored llm_analyses, never
   this run's fresh research.
2. `python -m app.main --with-screening --with-derivatives --with-macro
   --with-asset-intelligence --with-assessment --with-adversarial
   --with-judge --evaluate-outcomes`
3. `python -m scripts.apply_execution_costs`
   Zero LLM cost -- backfills realized_return_net_of_costs for whatever
   --evaluate-outcomes just resolved.
4. `python -m scripts.apply_benchmark_alpha`
   Zero LLM cost -- backfills benchmark_return/effective_alpha for the
   same newly-resolved decisions.

On Sundays only, a 5th step runs afterward:
5. `python -m scripts.run_reasoning_audit --sample-size 8`
   Real (but tiny, ~$0.003/decision) LLM cost -- samples from a fixed,
   non-growing pool of resolved backfilled decisions, so it doesn't need
   to run daily; once a week is enough to work through the backlog
   without adding it to every day's run (see doc/operations.md).

Each step is a real subprocess (not an in-process function call) so a
crash or `sys.exit()` in one step can't take this runner down with it, and
so each step sees a clean, independent process the same way it would if
you ran it by hand. Stops at the first step that fails (non-zero exit
code) rather than continuing on to steps that would read incomplete or
stale upstream data.

Usage:
    python -m scripts.run_daily
"""

import subprocess
import sys
from datetime import datetime

STEPS: list[list[str]] = [
    [sys.executable, "-m", "app.main", "--with-llm"],
    [
        sys.executable, "-m", "app.main",
        "--with-screening", "--with-derivatives", "--with-macro", "--with-asset-intelligence",
        "--with-assessment", "--with-adversarial", "--with-judge", "--evaluate-outcomes",
    ],
    [sys.executable, "-m", "scripts.apply_execution_costs"],
    [sys.executable, "-m", "scripts.apply_benchmark_alpha"],
]

# Only appended on Sundays (see build_steps) -- a fixed, non-growing pool
# of resolved backfilled decisions means there's nothing new to gain from
# running this more than about once a week.
SUNDAY_STEPS: list[list[str]] = [
    [sys.executable, "-m", "scripts.run_reasoning_audit", "--sample-size", "8"],
]


def build_steps(today: datetime | None = None) -> list[list[str]]:
    """`today` is injectable (rather than reading datetime.now() directly)
    so tests can pin a specific weekday without monkeypatching the
    datetime module itself."""
    today = today or datetime.now()
    steps = list(STEPS)
    if today.weekday() == 6:  # Monday=0 ... Sunday=6
        steps += SUNDAY_STEPS
    return steps


def run_steps(steps: list[list[str]]) -> int:
    for step in steps:
        print(f"\n=== Running: {' '.join(step)} ===", flush=True)
        result = subprocess.run(step)
        if result.returncode != 0:
            print(f"\nStopped -- step failed with exit code {result.returncode}: {' '.join(step)}")
            return result.returncode
    print("\n=== Daily sequence complete ===")
    return 0


def main() -> int:
    return run_steps(build_steps())


if __name__ == "__main__":
    sys.exit(main())
