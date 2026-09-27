from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import (
    get_calibration_run_repo,
    get_decision_outcome_repo,
    get_evidence_value_report_repo,
    get_judge_decision_repo,
    get_prompt_template_repo,
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
    PromptTemplateRepository,
    compute_duplicate_group_decision_ids,
)
from app.api.schemas import CalibrationSummary, PromptVersionBreakdown

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
    limit: int | None = None, is_backfilled: bool | None = None,
    repo: DecisionOutcomeRepository = Depends(get_decision_outcome_repo),
) -> list[DecisionOutcome]:
    """Newest-first. `limit=None` (2026-09-27, matching `/judge/decisions/
    recent` and `/assessments/research/recent`'s identical convention) now
    returns the complete population via `DecisionOutcomeRepository`'s
    pagination -- pass a real `limit` to cap the result if a caller wants
    a genuinely bounded recent slice instead."""
    return repo.get_recent(limit=limit, is_backfilled=is_backfilled)


@router.get("/evidence-value/recent", response_model=list[EvidenceValueReportRecord])
def get_recent_evidence_value_reports(
    limit: int = 50, repo: EvidenceValueReportRepository = Depends(get_evidence_value_report_repo),
) -> list[EvidenceValueReportRecord]:
    """3h's evidence-value ranking/drift reports — each tagged
    `sufficient_sample`; `false` means genuinely insufficient data, not a
    zero/negative finding."""
    return repo.get_recent(limit=limit)


def _directional_stats(pairs: list[tuple[DecisionOutcome, object]]) -> dict:
    """Hit-rate/Brier/Sharpe/DSR over one slice of (outcome, its own
    decision) pairs -- reused identically for the combined, backfilled-only,
    live-only, and per-prompt-version views below, so every reported figure
    is computed exactly the same way regardless of which subset it
    describes."""
    directional = []
    for o, decision in pairs:
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
    return {
        "directional_sample_size": len(directional),
        "hit_rate": hit_rate,
        "brier_score": brier_score,
        "sharpe_decision_level": sharpe,
        "deflated_sharpe_ratio": dsr,
    }


def _compute_embargo_stats(all_outcomes: list[DecisionOutcome]) -> dict:
    """Quantifies the README's Phase 3g "no embargo between the backfilled
    training window and the live holdout window" finding as a real,
    live-recomputed number instead of only a one-time historical
    observation -- uses EVERY backfilled/live decision regardless of
    resolution status (this is about when decisions were MADE, not
    whether they've resolved yet)."""
    backfilled = [o for o in all_outcomes if o.is_backfilled]
    live = [o for o in all_outcomes if not o.is_backfilled]
    if not backfilled or not live:
        return {"embargo_gap_days": None, "pct_live_within_own_horizon_of_training_end": None}

    training_end = max(o.decision_timestamp for o in backfilled)
    holdout_start = min(o.decision_timestamp for o in live)
    embargo_gap_days = (holdout_start - training_end).total_seconds() / 86400

    within_horizon_count = sum(
        1 for o in live
        if (o.decision_timestamp - training_end).total_seconds() / 86400 < o.horizon_days
    )
    pct_within = within_horizon_count / len(live)

    return {
        "embargo_gap_days": embargo_gap_days,
        "pct_live_within_own_horizon_of_training_end": pct_within,
    }


@router.get("/summary", response_model=CalibrationSummary)
def get_calibration_summary(
    outcome_repo: DecisionOutcomeRepository = Depends(get_decision_outcome_repo),
    judge_repo: JudgeDecisionRepository = Depends(get_judge_decision_repo),
    prompt_template_repo: PromptTemplateRepository = Depends(get_prompt_template_repo),
) -> CalibrationSummary:
    """Live-computed from real `decision_outcomes`/`judge_decisions` on
    every request (never a cached/stale figure) — resolved/unresolved
    counts split by backfilled vs. live (3e.1's non-negotiable), hit-rate/
    Brier/Sharpe/DSR on the resolved-and-directional sample, honestly
    reported as `null` wherever genuinely not computable, exactly the
    findings 3g/3h already established, re-derived live rather than
    hardcoded so this stays accurate as more decisions resolve.

    The top-level hit_rate/brier_score/sharpe_decision_level/
    deflated_sharpe_ratio are the COMBINED backfilled+live figure (kept for
    backward compatibility) -- but backfilled (simulated replay) and live
    (real forward-tracked) decisions are not the same statistical object,
    so the *_backfilled/*_live fields alongside them make the real split
    visible instead of only implying it via the separate resolved_*_count
    fields. by_prompt_version makes a second, orthogonal split visible too:
    a Judge prompt edit (this project has already shipped v1 -> v2) could
    otherwise silently blend two different methodologies into one number
    the moment any decision made under the older version resolves."""
    # limit=None (2026-09-27 follow-up, final DecisionOutcome migration
    # fix): the complete population, not just the first 2000 -- see
    # doc/decisions.md's 2026-09-27 entry. This was the one remaining
    # consumer the earlier batched migration (Phase 5q-5t) missed.
    all_outcomes = outcome_repo.get_recent(limit=None)
    resolved_backfilled = [o for o in all_outcomes if o.is_backfilled and o.outcome_label != "UNRESOLVED"]
    resolved_live = [o for o in all_outcomes if not o.is_backfilled and o.outcome_label != "UNRESOLVED"]
    unresolved_backfilled = [o for o in all_outcomes if o.is_backfilled and o.outcome_label == "UNRESOLVED"]
    unresolved_live = [o for o in all_outcomes if not o.is_backfilled and o.outcome_label == "UNRESOLVED"]

    resolved = resolved_backfilled + resolved_live
    # Fetched once per real resolved outcome (same real cost as the
    # original implementation) and reused across every view below, instead
    # of re-fetching per (combined, backfilled, live, per-version) slice.
    decision_by_outcome_id = {o.decision_id: judge_repo.get_by_id(o.decision_id) for o in resolved}

    # B2 (2026-09-16): same-UTC-day duplicate live Judge decisions (see
    # doc/history.md's Phase 5j section for the real 2026-09-05/06
    # incident) are excluded from every directional/calibration statistic
    # below -- hit_rate/brier_score/sharpe/DSR, combined and per-slice, and
    # by_prompt_version's per-template figures, via this one shared filter
    # in pairs_for(). Computed from the FULL live decision population, not
    # just resolved_live above, so group membership is correct and stable
    # even for a group with unresolved members (e.g. NEAR/2026-09-06) --
    # never recomputed differently as outcomes resolve. Deliberately does
    # NOT change resolved_backfilled_count/resolved_live_count/
    # unresolved_*_count below: those are raw audit counts of how many
    # decision_outcomes rows exist in each state, a distinct operational
    # statistic from calibration sample composition -- see doc/decisions.md.
    #
    # limit=None (2026-09-16 fix): duplicate-group membership must be
    # computed from the COMPLETE live decision population, never an
    # arbitrary recent-N slice -- a capped fetch could see only some
    # members of an old duplicate group (the rest pushed out of the
    # window by newer decisions) and wrongly conclude it isn't a
    # duplicate at all. Real per-request cost is negligible at this
    # project's actual scale (165 live decisions today); this is about
    # removing a correctness dependency on data volume, not performance.
    all_live_decisions = judge_repo.get_recent(limit=None, is_backfilled=False)
    excluded_decision_ids = compute_duplicate_group_decision_ids(
        (d.id, d.asset_id, d.created_at, d.is_backfilled) for d in all_live_decisions
    )

    def pairs_for(outcomes: list[DecisionOutcome]) -> list[tuple[DecisionOutcome, object]]:
        return [
            (o, decision_by_outcome_id.get(o.decision_id))
            for o in outcomes
            if o.decision_id not in excluded_decision_ids
        ]

    combined = _directional_stats(pairs_for(resolved))
    backfilled_stats = _directional_stats(pairs_for(resolved_backfilled))
    live_stats = _directional_stats(pairs_for(resolved_live))

    templates_by_id = prompt_template_repo.get_all()
    outcomes_by_template_id: dict[str, list[DecisionOutcome]] = {}
    for o in resolved:
        decision = decision_by_outcome_id.get(o.decision_id)
        if decision is None or not decision.prompt_template_id:
            continue
        outcomes_by_template_id.setdefault(decision.prompt_template_id, []).append(o)

    by_prompt_version = [
        PromptVersionBreakdown(
            prompt_template_id=template_id,
            version=templates_by_id.get(template_id, {}).get("version"),
            resolved_count=len(outcomes_for_template),
            directional_sample_size=(stats := _directional_stats(pairs_for(outcomes_for_template)))["directional_sample_size"],
            hit_rate=stats["hit_rate"],
        )
        for template_id, outcomes_for_template in outcomes_by_template_id.items()
    ]
    by_prompt_version.sort(key=lambda b: b.version or "")

    embargo_stats = _compute_embargo_stats(all_outcomes)

    total_live = len(resolved_live) + len(unresolved_live)
    held_out_window_note = (
        "No live (in_holdout_window=true) decisions exist yet."
        if total_live == 0
        else (
            "All in_holdout_window=true (live) decisions are currently "
            "UNRESOLVED -- insufficient data, not a null result. See "
            "README's Phase 3g held-out-window finding."
        ) if len(resolved_live) == 0
        else (
            f"{len(resolved_live)} of {total_live} live (in_holdout_window=true) "
            "decisions have resolved so far -- still a small sample, and there is "
            "no embargo gap between the backfilled training window and this live "
            "holdout window (see README's Phase 3g held-out-window finding), so "
            "treat hit_rate_live/sharpe_decision_level_live above as directionally "
            "suggestive only, not confirmatory."
            if embargo_stats["embargo_gap_days"] is None
            else (
                f"{len(resolved_live)} of {total_live} live (in_holdout_window=true) "
                "decisions have resolved so far -- still a small sample, and the real "
                f"embargo_gap_days above is {embargo_stats['embargo_gap_days']:.1f} "
                + (
                    "(negative -- the backfilled and live windows literally overlap "
                    "in wall-clock time)"
                    if embargo_stats["embargo_gap_days"] < 0
                    else "(no meaningful embargo -- see README's Phase 3g held-out-window finding)"
                )
                + f", and {embargo_stats['pct_live_within_own_horizon_of_training_end']:.0%} of live "
                "decisions are still within their own horizon's distance of the "
                "training-window boundary, so treat hit_rate_live/"
                "sharpe_decision_level_live above as directionally suggestive only, "
                "not confirmatory."
            )
        )
    )

    return CalibrationSummary(
        resolved_backfilled_count=len(resolved_backfilled),
        resolved_live_count=len(resolved_live),
        unresolved_backfilled_count=len(unresolved_backfilled),
        unresolved_live_count=len(unresolved_live),
        excluded_duplicate_group_decision_count=len(excluded_decision_ids),
        directional_sample_size=combined["directional_sample_size"],
        hit_rate=combined["hit_rate"],
        brier_score=combined["brier_score"],
        sharpe_decision_level=combined["sharpe_decision_level"],
        deflated_sharpe_ratio=combined["deflated_sharpe_ratio"],
        directional_sample_size_backfilled=backfilled_stats["directional_sample_size"],
        hit_rate_backfilled=backfilled_stats["hit_rate"],
        brier_score_backfilled=backfilled_stats["brier_score"],
        sharpe_decision_level_backfilled=backfilled_stats["sharpe_decision_level"],
        deflated_sharpe_ratio_backfilled=backfilled_stats["deflated_sharpe_ratio"],
        directional_sample_size_live=live_stats["directional_sample_size"],
        hit_rate_live=live_stats["hit_rate"],
        brier_score_live=live_stats["brier_score"],
        sharpe_decision_level_live=live_stats["sharpe_decision_level"],
        deflated_sharpe_ratio_live=live_stats["deflated_sharpe_ratio"],
        by_prompt_version=by_prompt_version,
        by_regime_note=(
            "Not computable: regime_at_decision is NULL on every resolved "
            "backfilled decision (3e.1's replay never persisted a real "
            "market_regime_snapshots row) -- a real persistence gap, not a "
            "sample-size problem. See README's Phase 3g/3h sections."
        ),
        held_out_window_note=held_out_window_note,
        embargo_gap_days=embargo_stats["embargo_gap_days"],
        pct_live_within_own_horizon_of_training_end=embargo_stats["pct_live_within_own_horizon_of_training_end"],
    )
