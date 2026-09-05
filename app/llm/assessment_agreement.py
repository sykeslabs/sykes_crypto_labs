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
