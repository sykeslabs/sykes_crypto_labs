"""Phase 3h tasks 1/1a: adaptive evidence-value ranking + drift detection,
run against the real `decision_outcomes` history.

Zero LLM cost — purely deterministic, using only structured fields already
persisted on `judge_decisions`/`decision_outcomes`. Same real dataset 3g
used for its Deflated Sharpe/Brier work (109 resolved backfilled outcomes,
36 directional), for consistency across sub-phases.

Real, honest limitation (see README's Phase 3h section): `source_assessment`
(per-named-evidence-source ranking) and `composite_factor_score` are NOT
joinable to any resolved decision — both are computed in-memory during
3e.1's replay but never persisted to real, queryable rows for backfilled
decisions (the same underlying gap 3g found for `regime_at_decision`). The
candidate feature set here is therefore restricted to fields genuinely
persisted on `judge_decisions` for every decision: model_agreement,
source_agreement, confidence, risk_score, uncertainty,
investment_horizon_days.

Usage:
    python scripts/run_evidence_value_ranking.py
"""

import sys
from collections import defaultdict
from datetime import UTC, datetime

from app.benchmarks.evidence_value import (
    MIN_SAMPLE_SIZE,
    TrainingExample,
    rank_evidence_value,
    regime_sliced_ranking,
    rolling_window_drift,
)
from app.benchmarks.schemas import EvidenceValueReportRecord
from app.database.client import get_supabase_client
from app.database.repository import DecisionOutcomeRepository, EvidenceValueReportRepository, JudgeDecisionRepository
from app.judge.schemas import JudgeDecisionRecord

FEATURE_FIELDS = [
    "model_agreement", "source_agreement", "confidence", "risk_score",
    "uncertainty", "investment_horizon_days",
]


def fetch_backfilled_decisions_chronological(client) -> list[JudgeDecisionRecord]:
    """Pagination-safe repository retrieval (2026-09-27 follow-up to B2).
    get_recent() orders DESCENDING by created_at; this consumer's own
    rolling-window drift analysis (task 1a) requires ASCENDING
    chronological order for its windows to mean what they claim to --
    reversed() restores that, it does not introduce a new query.

    Note (2026-09-27, DecisionOutcome consumer migration batch 3): this
    function's own ascending order is used only to build `dec_by_id`'s
    lookup dict below (a plain `.get()` target, order-irrelevant there) --
    it is NOT what makes `fetch_directional_examples`'s returned `examples`
    list chronological. That list is now explicitly sorted by its own
    `decision_outcomes.decision_timestamp` in `fetch_directional_examples`
    itself, closing the ordering gap this docstring used to flag as
    unresolved."""
    return list(reversed(JudgeDecisionRepository(client).get_recent(limit=None, is_backfilled=True)))


def fetch_directional_examples(client) -> list[TrainingExample]:
    decisions = fetch_backfilled_decisions_chronological(client)
    dec_by_id = {record.id: record for record in decisions}

    # Pagination-safe repository retrieval (2026-09-27 follow-up,
    # DecisionOutcome consumer migration batch 3): the old raw query was a
    # fully unbounded table scan (is_backfilled + resolved-only filter,
    # no `.range()`/`.limit()` at all) -- subject to Supabase's implicit
    # per-request row cap. get_recent() has no resolution filter of its
    # own, so the UNRESOLVED exclusion is applied in Python here,
    # preserving the exact original filter semantics.
    outcomes = [
        o for o in DecisionOutcomeRepository(client).get_recent(limit=None, is_backfilled=True)
        if o.outcome_label != "UNRESOLVED"
    ]
    # Ascending chronological order by the outcome's own real
    # decision_timestamp (2026-09-27): rolling_window_drift's own
    # docstring requires "examples must be chronologically ordered" for
    # its non-overlapping windows to mean what they claim to. The OLD raw
    # query had no `.order()` at all -- Postgres/PostgREST give no
    # ordering guarantee without one -- so this requirement was never
    # actually honored; the "windows" it produced were arbitrary chunks of
    # an undefined order, not real temporal slices. Sorting this complete,
    # already-resolved historical population by its own real timestamp is
    # not lookahead: every observation here already happened and already
    # resolved: this only makes the code's own stated chronological-window
    # intent actually true, for the first time.
    outcomes.sort(key=lambda o: o.decision_timestamp)

    examples = []
    for o in outcomes:
        d = dec_by_id.get(o.decision_id)
        if d is None or d.decision not in ("BUY", "SELL"):
            continue
        if any(getattr(d, f) is None for f in FEATURE_FIELDS):
            continue
        correct = (d.decision == "BUY" and o.realized_return > 0) or (d.decision == "SELL" and o.realized_return < 0)
        examples.append(TrainingExample(
            features={f: float(getattr(d, f)) for f in FEATURE_FIELDS},
            label=1 if correct else 0,
        ))
    return examples


def main() -> int:
    client = get_supabase_client()
    repo = EvidenceValueReportRepository(client)

    examples = fetch_directional_examples(client)
    print(f"Directional resolved backfilled decisions with all feature fields present: {len(examples)}")
    print(f"Candidate feature set: {FEATURE_FIELDS}")
    print(
        "NOTE: source_assessment and composite_factor_score are NOT usable here — "
        "not joinable to any resolved backfilled decision (see README's Phase 3h "
        "section for why)."
    )

    # Task 1: full-history ranking
    full_report = rank_evidence_value(examples, min_sample_size=MIN_SAMPLE_SIZE)
    print(f"\n=== Task 1: full-history ranking (n={full_report.sample_size}, min required={MIN_SAMPLE_SIZE}) ===")
    if not full_report.sufficient_sample:
        print(full_report.notes)
    else:
        for feature, importance in sorted(full_report.feature_importances.items(), key=lambda kv: -abs(kv[1])):
            print(f"  {feature}: {importance:+.4f}")
    repo.insert(EvidenceValueReportRecord(
        run_at=datetime.now(UTC), method=full_report.method, sample_size=full_report.sample_size,
        decision_outcomes_window="all_resolved_backfilled", feature_importances=full_report.feature_importances,
        sufficient_sample=full_report.sufficient_sample, notes=full_report.notes,
    ))

    # Task 1a: rolling-window drift (chronological, non-overlapping)
    window_size = 20
    rolling_reports = rolling_window_drift(examples, window_size=window_size, min_sample_size=MIN_SAMPLE_SIZE)
    print(f"\n=== Task 1a: rolling-window drift (window_size={window_size}) ===")
    for r in rolling_reports:
        print(f"  {r.method}: n={r.sample_size} sufficient={r.sufficient_sample}")
        if not r.sufficient_sample:
            print(f"    {r.notes}")
        repo.insert(EvidenceValueReportRecord(
            run_at=datetime.now(UTC), method=r.method, sample_size=r.sample_size,
            decision_outcomes_window=r.method, feature_importances=r.feature_importances,
            sufficient_sample=r.sufficient_sample, notes=r.notes,
        ))

    # Task 1a: regime-sliced (real limitation: regime_at_decision is NULL
    # for every backfilled decision -- same gap as above -- so there is
    # genuinely only one "regime" slice: UNKNOWN).
    print("\n=== Task 1a: regime-sliced drift ===")
    print(
        "NOT COMPUTABLE — regime_at_decision is NULL for every resolved "
        "backfilled decision (same persistence gap 3g found: replay computes "
        "a regime per simulated day but never persists it as a queryable "
        "row). There is no real regime label to slice by."
    )
    repo.insert(EvidenceValueReportRecord(
        run_at=datetime.now(UTC), method="regime_sliced[NOT_COMPUTABLE]", sample_size=len(examples),
        decision_outcomes_window="all_resolved_backfilled", feature_importances={}, sufficient_sample=False,
        notes=(
            "regime_at_decision is NULL for every resolved backfilled decision "
            "(same gap as 3g's regime-breakdown finding) -- no real regime "
            "label exists to slice by."
        ),
    ))

    return 0


if __name__ == "__main__":
    sys.exit(main())
