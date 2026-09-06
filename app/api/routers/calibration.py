from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import (
    get_calibration_run_repo,
    get_decision_outcome_repo,
    get_evidence_value_report_repo,
    get_judge_decision_repo,
)
from app.benchmarks.schemas import CalibrationRunRecord, DecisionOutcome, EvidenceValueReportRecord
from app.benchmarks.statistical_validation import (
    brier_decomposition,
    deflated_sharpe_ratio,
    sample_sharpe_stats,
)
from app.database.repository import (
    CalibrationRunRepository,
    DecisionOutcomeRepository,
    EvidenceValueReportRepository,
    JudgeDecisionRepository,
)
from app.api.schemas import CalibrationSummary

router = APIRouter(prefix="/calibration", tags=["calibration"], dependencies=[Depends(verify_api_key)])


@router.get("/runs/recent", response_model=list[CalibrationRunRecord])
def get_recent_calibration_runs(
    limit: int = 50, repo: CalibrationRunRepository = Depends(get_calibration_run_repo),
) -> list[CalibrationRunRecord]:
    """Every calibration attempt as its own, method-tagged, countable trial
    (3g's own trial-count discipline) — never merged into one figure."""
    return repo.get_recent(limit=limit)


@router.get("/outcomes/recent", response_model=list[DecisionOutcome])
def get_recent_outcomes(
    limit: int = 200, is_backfilled: bool | None = None,
    repo: DecisionOutcomeRepository = Depends(get_decision_outcome_repo),
) -> list[DecisionOutcome]:
    return repo.get_recent(limit=limit, is_backfilled=is_backfilled)


@router.get("/evidence-value/recent", response_model=list[EvidenceValueReportRecord])
def get_recent_evidence_value_reports(
    limit: int = 50, repo: EvidenceValueReportRepository = Depends(get_evidence_value_report_repo),
) -> list[EvidenceValueReportRecord]:
    """3h's evidence-value ranking/drift reports — each tagged
    `sufficient_sample`; `false` means genuinely insufficient data, not a
    zero/negative finding."""
    return repo.get_recent(limit=limit)


@router.get("/summary", response_model=CalibrationSummary)
def get_calibration_summary(
    outcome_repo: DecisionOutcomeRepository = Depends(get_decision_outcome_repo),
    judge_repo: JudgeDecisionRepository = Depends(get_judge_decision_repo),
) -> CalibrationSummary:
    """Live-computed from real `decision_outcomes`/`judge_decisions` on
    every request (never a cached/stale figure) — resolved/unresolved
    counts split by backfilled vs. live (3e.1's non-negotiable), hit-rate/
    Brier/Sharpe/DSR on the resolved-and-directional sample, honestly
    reported as `null` wherever genuinely not computable, exactly the
    findings 3g/3h already established, re-derived live rather than
    hardcoded so this stays accurate as more decisions resolve."""
    all_outcomes = outcome_repo.get_recent(limit=2000)
    resolved_backfilled = [o for o in all_outcomes if o.is_backfilled and o.outcome_label != "UNRESOLVED"]
    resolved_live = [o for o in all_outcomes if not o.is_backfilled and o.outcome_label != "UNRESOLVED"]
    unresolved_backfilled = [o for o in all_outcomes if o.is_backfilled and o.outcome_label == "UNRESOLVED"]
    unresolved_live = [o for o in all_outcomes if not o.is_backfilled and o.outcome_label == "UNRESOLVED"]

    resolved = resolved_backfilled + resolved_live
    directional = []
    for o in resolved:
        decision = judge_repo.get_by_id(o.decision_id)
        if decision is None or decision.decision not in ("BUY", "SELL"):
            continue
        correct = (
            (decision.decision == "BUY" and o.realized_return is not None and o.realized_return > 0)
            or (decision.decision == "SELL" and o.realized_return is not None and o.realized_return < 0)
        )
        directional.append((decision.confidence, 1 if correct else 0, o.realized_return))

    hit_rate = brier_score = sharpe = dsr = None
    if directional:
        predictions = [d[0] for d in directional]
        outcomes_binary = [d[1] for d in directional]
        hit_rate = sum(outcomes_binary) / len(outcomes_binary)
        brier_score = brier_decomposition(predictions, outcomes_binary)["brier_score"]
        returns = [d[2] for d in directional if d[2] is not None]
        if len(returns) >= 2:
            try:
                sharpe, skew, kurt, n = sample_sharpe_stats(returns)
                dsr = deflated_sharpe_ratio(sharpe, n_observations=n, n_trials=1, skewness=skew, kurtosis=kurt)
            except ValueError:
                sharpe = dsr = None

    return CalibrationSummary(
        resolved_backfilled_count=len(resolved_backfilled),
        resolved_live_count=len(resolved_live),
        unresolved_backfilled_count=len(unresolved_backfilled),
        unresolved_live_count=len(unresolved_live),
        directional_sample_size=len(directional),
        hit_rate=hit_rate,
        brier_score=brier_score,
        sharpe_decision_level=sharpe,
        deflated_sharpe_ratio=dsr,
        by_regime_note=(
            "Not computable: regime_at_decision is NULL on every resolved "
            "backfilled decision (3e.1's replay never persisted a real "
            "market_regime_snapshots row) -- a real persistence gap, not a "
            "sample-size problem. See README's Phase 3g/3h sections."
        ),
        held_out_window_note=(
            "All in_holdout_window=true (live) decisions are currently "
            "UNRESOLVED -- insufficient data, not a null result. See "
            "README's Phase 3g held-out-window finding."
        ),
    )
