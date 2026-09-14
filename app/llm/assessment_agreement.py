"""Model-agreement computation for 3d — a directional-agreement measure,
computed once per asset per run across all configured models' responses.
Distinct from any individual model's confidence (per the 3d non-negotiable):
this measures whether models agree with EACH OTHER, not how sure any one of
them is.
"""


def compute_model_agreement(overall_assessments: list[str]) -> float:
    """Fraction of models agreeing with the majority `overall_assessment`
    direction. 1.0 if only one model produced a usable assessment (nothing
    to disagree with) or if every model agrees; lower values reflect genuine
    split opinion. 0.0 for an empty list (no assessments at all)."""
    if not overall_assessments:
        return 0.0
    if len(overall_assessments) == 1:
        return 1.0

    counts: dict[str, int] = {}
    for direction in overall_assessments:
        counts[direction] = counts.get(direction, 0) + 1
    majority_count = max(counts.values())
    return majority_count / len(overall_assessments)


def compute_return_dispersion(expected_returns: list[float]) -> float | None:
    """Continuous complement to `compute_model_agreement`'s coarse
    majority-vote fraction (real observed history: only 1.0 or 0.667 ever
    occur at n=3 models, since `overall_assessment`'s 3 categories rarely
    split three ways) -- see the dashboard's own `[HIGH][AI] model_agreement`
    TODO. Reports the real dispersion (population standard deviation) of the
    models' own `expected_return_30d` figures, in the same return-fraction
    units, rather than forcing it into an invented 0-1 "agreement" score
    (which would need an unvalidated scale constant to say what counts as
    "full disagreement").

    A real 2-1 majority split where the two agreeing models differ by 40
    percentage points in their expected return looks identical to
    `compute_model_agreement` as one where they differ by 2 points --
    `overall_assessment` only captures a discrete DIRECTION match, never the
    real spread in MAGNITUDE. This is additive, not a replacement:
    `model_agreement` is unchanged and still the only agreement figure fed
    into the Risk Engine's sizing scalar (`app/risk/engine.py`) -- this is a
    new, disclosed, not-yet-validated signal for future backtesting (same
    "checking, not decision-making" role as `app/benchmarks/evidence_value.py`),
    surfaced for visibility, not wired into any live decision yet.

    None if fewer than 2 real values are available (nothing to compute a
    spread from) -- never fabricated as 0."""
    if len(expected_returns) < 2:
        return None
    n = len(expected_returns)
    mean = sum(expected_returns) / n
    variance = sum((r - mean) ** 2 for r in expected_returns) / n
    return variance**0.5
