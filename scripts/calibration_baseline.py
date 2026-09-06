"""Phase 3e task 5 (+ 3e.1 task 6): baseline calibration script.

Two independent modes, always reported and persisted SEPARATELY, never
combined into one number (per 3e.1's non-negotiable):

--source phase2 (default): checks whether Phase 1/2's EXISTING `llm_analyses`
  directional calls correlated with subsequent price movement, using only
  historical data already in Supabase (`market_snapshots` + `llm_analyses`).

--source backfill: checks 3e.1's backfilled `judge_decisions`/
  `decision_outcomes` rows (is_backfilled=true) the same way, using their
  richer BUY/HOLD/SELL/WATCH/NO_TRADE vocabulary and already-resolved
  `realized_return`/`outcome_label`.

Both report two distinct things, not one:
  - Directional hit-rate (was the call right).
  - Calibration: a Brier score between stated confidence and realized
    outcome, plus a reliability breakdown by confidence bucket. A system can
    have a fine hit-rate and still be badly over/underconfident — a
    different failure mode from directional accuracy.

Persists the result as a row in `calibration_runs` — a countable, first-class
attempt (per PHASE3E_PROMPT.md task 5), since 3g's deflated-Sharpe/PBO
correction needs an honest count of every calibration attempt, not just
resolved decisions. `method` distinguishes which mode produced the row
(`phase2_llm_analyses_directional_baseline` vs. `BACKFILL_BASELINE`) so 3g
can tell them apart.

This is a lightweight baseline, not full research-grade backtesting: HOLD/
WATCH/NO_TRADE rows are excluded from hit-rate/Brier (no directional claim
to score against — a real scoping decision, not an oversight). The phase2
mode uses a single fixed --horizon-days for every row (Phase 2 predates
per-decision horizons); the backfill mode uses each decision's own
already-resolved outcome instead.

Usage:
    python scripts/calibration_baseline.py --source phase2 [--horizon-days 7]
    python scripts/calibration_baseline.py --source backfill
"""

import argparse
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from app.benchmarks.schemas import CalibrationRunRecord
from app.database.client import get_supabase_client
from app.database.repository import CalibrationRunRepository

HORIZON_DAYS_DEFAULT = 7


def fetch_llm_analyses(client) -> list[dict]:
    response = client.table("llm_analyses").select("*").order("timestamp").execute()
    return response.data


def fetch_price_at_or_after(client, asset_id: str, ts: datetime) -> dict | None:
    response = (
        client.table("market_snapshots")
        .select("price,timestamp")
        .eq("asset_id", asset_id)
        .gte("timestamp", ts.isoformat())
        .order("timestamp")
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def _score_directional(rows: list[dict]) -> tuple[list[dict], float | None, float | None, dict]:
    """Shared scoring: `rows` are {action, confidence, realized_return}
    dicts already filtered to a directional (BUY/SELL) claim with a real
    realized_return. Returns (directional_rows, hit_rate, brier_score, buckets)."""
    brier_terms = []
    buckets: dict[float, dict[str, int]] = defaultdict(lambda: {"hits": 0, "count": 0})
    hits = 0
    for r in rows:
        correct = (r["action"] == "BUY" and r["realized_return"] > 0) or (
            r["action"] == "SELL" and r["realized_return"] < 0
        )
        outcome = 1.0 if correct else 0.0
        hits += int(correct)
        brier_terms.append((r["confidence"] - outcome) ** 2)
        bucket = round(r["confidence"] * 5) / 5  # quintile-ish bucketing
        buckets[bucket]["count"] += 1
        buckets[bucket]["hits"] += int(correct)

    hit_rate = hits / len(rows) if rows else None
    brier_score = sum(brier_terms) / len(brier_terms) if brier_terms else None
    return rows, hit_rate, brier_score, buckets


def _print_report(directional, hit_rate, brier_score, buckets, resolved_count) -> None:
    print(f"Directional rows scored: {len(directional)}")
    print(f"Hit rate: {hit_rate}")
    print(f"Brier score: {brier_score}")
    print("Reliability by confidence bucket:")
    for bucket in sorted(buckets):
        b = buckets[bucket]
        print(f"  confidence~{bucket}: hit_rate={b['hits'] / b['count']:.3f} (n={b['count']})")


def run_phase2_baseline(client, horizon_days: int) -> int:
    analyses = fetch_llm_analyses(client)
    print(f"Found {len(analyses)} llm_analyses rows.")
    if not analyses:
        print("Nothing to calibrate against yet.")
        return 0

    resolved = []
    for row in analyses:
        ts = datetime.fromisoformat(row["timestamp"])
        entry = fetch_price_at_or_after(client, row["asset_id"], ts)
        if entry is None:
            continue
        exit_row = fetch_price_at_or_after(client, row["asset_id"], ts + timedelta(days=horizon_days))
        if exit_row is None:
            continue  # not enough time has passed yet for this row's horizon

        entry_price, exit_price = float(entry["price"]), float(exit_row["price"])
        if entry_price == 0:
            continue
        resolved.append({
            "action": row["action"],
            "confidence": float(row["confidence"]),
            "realized_return": (exit_price / entry_price) - 1,
        })

    print(f"Resolved {len(resolved)} rows with both entry and horizon-end prices available.")
    directional = [r for r in resolved if r["action"] in ("BUY", "SELL")]
    directional, hit_rate, brier_score, buckets = _score_directional(directional)
    _print_report(directional, hit_rate, brier_score, buckets, len(resolved))

    # Phase 2 predates 3a's `prompt_templates` table — its `llm_analyses`
    # rows only carry a free-text `prompt_version`, not a real template id.
    # Recorded as-is rather than fabricating a template id that never existed.
    prompt_versions = sorted({row["prompt_version"] for row in analyses})

    record = CalibrationRunRecord(
        run_at=datetime.now(UTC),
        method="phase2_llm_analyses_directional_baseline",
        sample_size=len(directional),
        prompt_template_ids=prompt_versions,
        hit_rate=hit_rate,
        brier_score=brier_score,
        notes=(
            f"horizon_days={horizon_days}; HOLD rows excluded from hit-rate/Brier "
            f"(no directional claim); {len(resolved) - len(directional)} HOLD rows resolved "
            f"but not scored; prompt_template_ids here are Phase 2's free-text prompt_version "
            f"values, not real prompt_templates.id rows (Phase 2 predates that table)."
        ),
    )
    CalibrationRunRepository(client).insert(record)
    print("Persisted to calibration_runs (method=phase2_llm_analyses_directional_baseline).")
    return 0


def run_backfill_baseline(client) -> int:
    decisions = (
        client.table("judge_decisions").select("id,decision,confidence,prompt_template_id")
        .eq("is_backfilled", True).execute().data
    )
    print(f"Found {len(decisions)} backfilled judge_decisions rows.")
    if not decisions:
        print("Nothing to calibrate against yet — run scripts/run_replay.py first.")
        return 0

    decision_ids = [d["id"] for d in decisions]
    outcomes = (
        client.table("decision_outcomes").select("decision_id,realized_return,outcome_label")
        .in_("decision_id", decision_ids).neq("outcome_label", "UNRESOLVED").execute().data
    )
    outcome_by_decision = {o["decision_id"]: o for o in outcomes}
    print(f"Resolved (non-UNRESOLVED) backfilled outcomes: {len(outcomes)}")

    resolved = []
    for d in decisions:
        outcome = outcome_by_decision.get(d["id"])
        if outcome is None or outcome["realized_return"] is None:
            continue
        resolved.append({
            "action": d["decision"],
            "confidence": float(d["confidence"]),
            "realized_return": float(outcome["realized_return"]),
        })

    directional = [r for r in resolved if r["action"] in ("BUY", "SELL")]
    directional, hit_rate, brier_score, buckets = _score_directional(directional)
    _print_report(directional, hit_rate, brier_score, buckets, len(resolved))

    prompt_template_ids = sorted({d["prompt_template_id"] for d in decisions if d["prompt_template_id"]})

    record = CalibrationRunRecord(
        run_at=datetime.now(UTC),
        method="BACKFILL_BASELINE",
        sample_size=len(directional),
        prompt_template_ids=prompt_template_ids,
        hit_rate=hit_rate,
        brier_score=brier_score,
        notes=(
            f"HOLD/WATCH/NO_TRADE rows excluded from hit-rate/Brier (no directional claim); "
            f"{len(resolved) - len(directional)} such rows resolved but not scored. Backfilled-window "
            f"accuracy — never combined with the forward-tracked (phase2/live) baseline (per "
            f"PHASE3E1_PROMPT.md's non-negotiable)."
        ),
    )
    CalibrationRunRepository(client).insert(record)
    print("Persisted to calibration_runs (method=BACKFILL_BASELINE).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="3e/3e.1 baseline calibration script")
    parser.add_argument("--source", choices=["phase2", "backfill"], default="phase2")
    parser.add_argument("--horizon-days", type=int, default=HORIZON_DAYS_DEFAULT, help="Only used for --source phase2.")
    args = parser.parse_args()

    client = get_supabase_client()
    if args.source == "phase2":
        return run_phase2_baseline(client, args.horizon_days)
    return run_backfill_baseline(client)


if __name__ == "__main__":
    sys.exit(main())
