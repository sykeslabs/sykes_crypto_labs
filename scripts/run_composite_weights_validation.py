"""Fixes the `[HIGH][Quant] COMPOSITE_FACTOR_WEIGHTS was never empirically
validated against forward returns` TODO -- checks whether the live
momentum-tilted weighting actually selects better-performing assets than an
equal-weight or a momentum-only alternative, using every real resolved
directional (BUY/SELL) decision that is genuinely joinable back to its own
screened_universe peer group (i.e. the full set of assets screened
alongside it on the same run, needed to recompute percentile-rank-based
scores under an alternative weighting).

Real, disclosed limitation: this join only exists for LIVE decisions
(screening always persisted `screened_universe` for live runs) and for
BACKFILLED decisions made *after* 2026-09-12's replay.py persistence fix
(see the `[HIGH][Data] regime_at_decision/composite_factor_score
persistence gap` TODO) -- the 111 backfilled decisions from before that fix
have no joinable screened_universe row at all and are excluded here, not
silently treated as zero/neutral.

Zero LLM cost -- purely deterministic, reusing already-persisted
screened_universe/judge_decisions/decision_outcomes rows and
app.market_data.factors' own ranking function (extended with an optional
`weights` override for this exact purpose).

Usage:
    python -m scripts.run_composite_weights_validation
"""

import sys
from datetime import UTC, datetime

from app.benchmarks.schemas import CalibrationRunRecord
from app.database.client import get_supabase_client
from app.database.repository import (
    CalibrationRunRepository,
    DecisionOutcomeRepository,
    JudgeDecisionRepository,
    compute_duplicate_group_decision_ids,
)
from app.market_data.factors import COMPOSITE_FACTOR_WEIGHTS, compute_composite_factor_scores

FACTOR_FIELDS = list(COMPOSITE_FACTOR_WEIGHTS)

EQUAL_WEIGHTS = {name: 1.0 / len(FACTOR_FIELDS) for name in FACTOR_FIELDS}
MOMENTUM_ONLY_WEIGHTS = {name: (1.0 if name == "momentum_30d" else 0.0) for name in FACTOR_FIELDS}

# Same rule-of-thumb bar app/benchmarks/evidence_value.py uses for its own
# logistic-regression ranking -- reused here for consistency across the
# dashboard's "is this backtest big enough to trust" reporting, not because
# a simple correlation needs exactly this many observations.
MIN_SAMPLE_SIZE = 50


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / (var_x**0.5 * var_y**0.5)


def fetch_joinable_directional_examples(client) -> list[dict]:
    """One entry per resolved directional decision that has a real,
    joinable screened_universe peer group -- {label (1=correct/0=wrong),
    realized_return, current_score, equal_weight_score, momentum_only_score}.

    B2 (2026-09-16): same-UTC-day duplicate LIVE Judge decisions (see
    doc/history.md's Phase 5j section) are excluded here too, the same way
    and for the same reason as app/api/routers/calibration.py -- this
    script reads the identical unfiltered live population and would
    otherwise silently double-count the same historical duplicate group(s)
    in its own correlation/mean-score figures."""
    outcome_repo = DecisionOutcomeRepository(client)
    judge_repo = JudgeDecisionRepository(client)

    all_outcomes = outcome_repo.get_recent(limit=2000)
    resolved = [o for o in all_outcomes if o.outcome_label != "UNRESOLVED"]

    # Computed from the FULL live decision population (not just resolved
    # ones), so group membership is correct and stable regardless of which
    # members have resolved so far -- see compute_duplicate_group_decision_ids's
    # own docstring. limit=None (2026-09-16 fix): a capped fetch could see
    # only some members of an old duplicate group and wrongly conclude it
    # isn't a duplicate at all -- see app/api/routers/calibration.py's
    # identical fix for the full reasoning.
    all_live_decisions = judge_repo.get_recent(limit=None, is_backfilled=False)
    excluded_decision_ids = compute_duplicate_group_decision_ids(
        (d.id, d.asset_id, d.created_at, d.is_backfilled) for d in all_live_decisions
    )

    examples = []
    skipped_no_screening_row = 0
    skipped_duplicate_group = 0
    for o in resolved:
        if o.decision_id in excluded_decision_ids:
            skipped_duplicate_group += 1
            continue
        decision = judge_repo.get_by_id(o.decision_id)
        if decision is None or decision.decision not in ("BUY", "SELL"):
            continue

        own_row_resp = (
            client.table("screened_universe")
            .select("*")
            .eq("run_id", decision.run_id)
            .eq("asset_id", decision.asset_id)
            .limit(1)
            .execute()
        )
        if not own_row_resp.data:
            skipped_no_screening_row += 1
            continue

        peer_rows_resp = client.table("screened_universe").select("*").eq("run_id", decision.run_id).execute()
        peer_rows = peer_rows_resp.data
        factor_rows = [{f: row.get(f) for f in FACTOR_FIELDS} for row in peer_rows]
        own_index = next(i for i, row in enumerate(peer_rows) if row["asset_id"] == decision.asset_id)

        current_scores = compute_composite_factor_scores(factor_rows)  # live real weights, unchanged behavior
        equal_scores = compute_composite_factor_scores(factor_rows, weights=EQUAL_WEIGHTS)
        momentum_scores = compute_composite_factor_scores(factor_rows, weights=MOMENTUM_ONLY_WEIGHTS)

        current_score = current_scores[own_index]
        equal_score = equal_scores[own_index]
        momentum_score = momentum_scores[own_index]
        if current_score is None or equal_score is None or momentum_score is None:
            continue

        correct = (
            (decision.decision == "BUY" and o.realized_return is not None and o.realized_return > 0)
            or (decision.decision == "SELL" and o.realized_return is not None and o.realized_return < 0)
        )
        examples.append({
            "label": 1 if correct else 0,
            "realized_return": o.realized_return,
            "current_score": current_score,
            "equal_weight_score": equal_score,
            "momentum_only_score": momentum_score,
            "is_backfilled": o.is_backfilled,
        })

    return examples, skipped_no_screening_row, skipped_duplicate_group


def main() -> int:
    client = get_supabase_client()
    calibration_run_repo = CalibrationRunRepository(client)

    examples, skipped_no_screening_row, skipped_duplicate_group = fetch_joinable_directional_examples(client)
    n = len(examples)
    n_backfilled = sum(1 for e in examples if e["is_backfilled"])
    n_live = n - n_backfilled
    print(f"Resolved directional decisions with a joinable screened_universe peer group: {n} ({n_backfilled} backfilled, {n_live} live)")
    print(f"Resolved directional decisions skipped -- no joinable screened_universe row: {skipped_no_screening_row}")
    print(f"Resolved directional decisions skipped -- same-day live duplicate group (B2): {skipped_duplicate_group}")
    print(
        "(Backfilled decisions are only joinable if made after 2026-09-12's replay.py "
        "persistence fix -- every earlier backfilled decision has no screened_universe row "
        "at all and is correctly excluded above, not treated as zero/neutral.)"
    )

    results = {}
    for scheme, score_key in [
        ("current_weights", "current_score"),
        ("equal_weights", "equal_weight_score"),
        ("momentum_only", "momentum_only_score"),
    ]:
        scores = [e[score_key] for e in examples]
        labels = [float(e["label"]) for e in examples]
        returns_with_scores = [(e[score_key], e["realized_return"]) for e in examples if e["realized_return"] is not None]

        corr_with_correctness = _pearson(scores, labels) if n >= 2 else None
        corr_with_return = (
            _pearson([s for s, _ in returns_with_scores], [r for _, r in returns_with_scores])
            if len(returns_with_scores) >= 2 else None
        )
        correct_scores = [e[score_key] for e in examples if e["label"] == 1]
        incorrect_scores = [e[score_key] for e in examples if e["label"] == 0]
        mean_score_correct = sum(correct_scores) / len(correct_scores) if correct_scores else None
        mean_score_incorrect = sum(incorrect_scores) / len(incorrect_scores) if incorrect_scores else None

        results[scheme] = {
            "corr_with_correctness": corr_with_correctness,
            "corr_with_realized_return": corr_with_return,
            "mean_score_correct_decisions": mean_score_correct,
            "mean_score_incorrect_decisions": mean_score_incorrect,
        }
        print(f"\n=== {scheme} ===")
        print(f"  correlation(score, directionally-correct 0/1) = {corr_with_correctness}")
        print(f"  correlation(score, realized_return)            = {corr_with_return}")
        print(f"  mean score | correct decisions   = {mean_score_correct}")
        print(f"  mean score | incorrect decisions = {mean_score_incorrect}")

    sufficient_sample = n >= MIN_SAMPLE_SIZE
    notes = (
        f"n={n} resolved directional decisions with a real joinable screened_universe peer "
        f"group ({n_backfilled} backfilled [only possible after 2026-09-12's persistence fix], "
        f"{n_live} live); {skipped_no_screening_row} resolved directional decisions skipped, no "
        f"joinable screening row. "
        + (
            f"INSUFFICIENT SAMPLE (below the {MIN_SAMPLE_SIZE}-observation bar "
            "app/benchmarks/evidence_value.py's own logistic regression uses) -- the "
            "correlations above are real but not yet trustworthy evidence for or against the "
            "current weighting; do not treat any of the three schemes as validated or "
            "invalidated on this sample. Re-run once n is much larger."
            if not sufficient_sample else
            "Sample now clears the same 50-observation bar evidence_value.py uses -- see the "
            "per-scheme correlations above for a real signal on whether the current weighting "
            "outperforms equal-weight/momentum-only alternatives."
        )
        + f" Per-scheme results: {results}"
    )
    calibration_run_repo.insert(CalibrationRunRecord(
        run_at=datetime.now(UTC), method="composite_factor_weights_validation",
        sample_size=n, hit_rate=None, brier_score=None, notes=notes,
    ))
    print(f"\nSufficient sample (n >= {MIN_SAMPLE_SIZE})? {sufficient_sample}")
    print("Real CalibrationRunRecord persisted (method=composite_factor_weights_validation).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
