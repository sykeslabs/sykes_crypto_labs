"""Phase 3e task 5: baseline calibration script.

Checks whether Phase 1/2's EXISTING `llm_analyses` directional calls
correlated with subsequent price movement, using only historical data
already in Supabase (`market_snapshots` + `llm_analyses`) — no live API/LLM
calls. Reports two distinct things, not one:
  - Directional hit-rate (was the call right).
  - Calibration: a Brier score between stated confidence and realized
    outcome, plus a reliability breakdown by confidence bucket. A system can
    have a fine hit-rate and still be badly over/underconfident — a
    different failure mode from directional accuracy.

Persists the result as a row in `calibration_runs` — a countable, first-class
attempt (per PHASE3E_PROMPT.md task 5), since 3g's deflated-Sharpe/PBO
correction needs an honest count of every calibration attempt, not just
resolved decisions.

This is a lightweight baseline, not full research-grade backtesting: HOLD
rows are excluded from hit-rate/Brier (no directional claim to score against
— a real scoping decision, not an oversight), and the horizon is a single
fixed --horizon-days for every row rather than per-row logic derived from
Phase 2's free-text `investment_horizon` field.

Usage: python scripts/calibration_baseline.py [--horizon-days 7]
"""

import argparse
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from app.database.client import get_supabase_client
from app.benchmarks.schemas import CalibrationRunRecord
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


def main() -> int:
    parser = argparse.ArgumentParser(description="3e baseline calibration script")
    parser.add_argument("--horizon-days", type=int, default=HORIZON_DAYS_DEFAULT)
    args = parser.parse_args()

    client = get_supabase_client()

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
        exit_row = fetch_price_at_or_after(client, row["asset_id"], ts + timedelta(days=args.horizon_days))
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
    brier_terms = []
    buckets: dict[float, dict[str, int]] = defaultdict(lambda: {"hits": 0, "count": 0})
    hits = 0
    for r in directional:
        correct = (r["action"] == "BUY" and r["realized_return"] > 0) or (
            r["action"] == "SELL" and r["realized_return"] < 0
        )
        outcome = 1.0 if correct else 0.0
        hits += int(correct)
        brier_terms.append((r["confidence"] - outcome) ** 2)
        bucket = round(r["confidence"] * 5) / 5  # quintile-ish bucketing
        buckets[bucket]["count"] += 1
        buckets[bucket]["hits"] += int(correct)

    hit_rate = hits / len(directional) if directional else None
    brier_score = sum(brier_terms) / len(brier_terms) if brier_terms else None

    print(f"Directional (BUY/SELL) rows scored: {len(directional)}")
    print(f"Hit rate: {hit_rate}")
    print(f"Brier score: {brier_score}")
    print("Reliability by confidence bucket:")
    for bucket in sorted(buckets):
        b = buckets[bucket]
        print(f"  confidence~{bucket}: hit_rate={b['hits'] / b['count']:.3f} (n={b['count']})")

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
            f"horizon_days={args.horizon_days}; HOLD rows excluded from hit-rate/Brier "
            f"(no directional claim); {len(resolved) - len(directional)} HOLD rows resolved "
            f"but not scored; prompt_template_ids here are Phase 2's free-text prompt_version "
            f"values, not real prompt_templates.id rows (Phase 2 predates that table)."
        ),
    )
    CalibrationRunRepository(client).insert(record)
    print("Persisted to calibration_runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
