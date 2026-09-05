"""Forward-looking decision vocabulary for the Judge (built in 3e).

`DecisionValue` is intentionally separate from Phase 2's `Action`
(`app/llm/schemas.py`, BUY/HOLD/SELL only, used by real validated LLM
output) — this sub-phase (3a) only needs the value NO_TRADE (and WATCH) to
exist somewhere; no decision-making logic is built yet. Keeping the two
types separate means Phase 2's live schema is never touched by this.

Enforced today only at the database level: `judge_decisions.decision` (see
migrations/0003_phase3a_universe_provenance.sql) has a CHECK constraint over
this same five-value set.
"""

from typing import Literal

DecisionValue = Literal["BUY", "HOLD", "SELL", "WATCH", "NO_TRADE"]
