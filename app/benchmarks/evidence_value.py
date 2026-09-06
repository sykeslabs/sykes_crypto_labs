"""Phase 3h task 1/1a: adaptive evidence-value ranking + drift detection.

A simple, inspectable logistic regression — implemented from scratch via
batch gradient descent, no new ML dependency added. This project already
declines new tooling that doesn't match a specific, scoped need (see
README's "Technology stack decisions"), and a hand-rolled logistic
regression over a handful of features and (currently) a few dozen real
observations is fully tractable in pure Python; scikit-learn/numpy would be
real, unjustified new dependencies for a problem this small.

This is a CHECKING model, never a decision-maker (per PHASE3H_PROMPT.md's
own non-negotiable): its only consumer is the report it produces. It is
never wired into the live Judge/Risk Engine pipeline to auto-reweight
evidence.
"""

import math
from dataclasses import dataclass, field

# ~10 observations per candidate feature is a common, conservative
# rule-of-thumb minimum for a stable logistic-regression fit (Peduzzi et al.
# 1996, "A simulation study of the number of events per variable in
# logistic regression analysis"). This project's real candidate feature set
# (model_agreement, source_agreement, confidence, risk_score, uncertainty,
# investment_horizon_days) has up to 6 fields, implying ~60 by the strict
# rule; 50 is used here as a slightly relaxed but still defensible bar,
# reachable as more decisions resolve rather than set arbitrarily high to
# guarantee "insufficient data" forever.
MIN_SAMPLE_SIZE = 50


@dataclass
class TrainingExample:
    features: dict[str, float]
    label: int  # 1 = correct, 0 = incorrect


@dataclass
class EvidenceValueReport:
    method: str
    sample_size: int
    feature_importances: dict[str, float] = field(default_factory=dict)
    sufficient_sample: bool = False
    notes: str = ""


def _standardize(values: list[float]) -> list[float]:
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    stdev = math.sqrt(variance)
    if stdev == 0:
        return [0.0 for _ in values]
    return [(v - mean) / stdev for v in values]


def _sigmoid(z: float) -> float:
    # Numerically stable form -- avoids overflow in math.exp for large |z|.
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1 + exp_z)


def train_logistic_regression(
    examples: list[TrainingExample],
    learning_rate: float = 0.3,
    iterations: int = 3000,
    l2: float = 0.05,
) -> dict[str, float]:
    """Batch gradient descent on standardized features (so a coefficient's
    magnitude is directly comparable across features measured on different
    original scales), with a small L2 penalty for stability on a small
    sample. Returns {feature_name: coefficient}, plus "_intercept_"."""
    if not examples:
        raise ValueError("no training examples")

    feature_names = sorted(examples[0].features.keys())
    n = len(examples)
    standardized_columns = {
        name: _standardize([ex.features[name] for ex in examples]) for name in feature_names
    }
    labels = [ex.label for ex in examples]

    weights = {name: 0.0 for name in feature_names}
    intercept = 0.0

    for _ in range(iterations):
        grad_w = {name: 0.0 for name in feature_names}
        grad_b = 0.0
        for i in range(n):
            z = intercept + sum(weights[name] * standardized_columns[name][i] for name in feature_names)
            error = _sigmoid(z) - labels[i]
            for name in feature_names:
                grad_w[name] += error * standardized_columns[name][i]
            grad_b += error
        for name in feature_names:
            weights[name] -= learning_rate * (grad_w[name] / n + l2 * weights[name])
        intercept -= learning_rate * (grad_b / n)

    result = dict(weights)
    result["_intercept_"] = intercept
    return result


def rank_evidence_value(
    examples: list[TrainingExample], min_sample_size: int = MIN_SAMPLE_SIZE, method: str = "full_history_logistic_regression",
) -> EvidenceValueReport:
    n = len(examples)
    if n < min_sample_size:
        return EvidenceValueReport(
            method=method, sample_size=n, feature_importances={}, sufficient_sample=False,
            notes=(
                f"insufficient data: n={n} resolved directional decisions available, "
                f"below the required minimum of {min_sample_size} (~10 observations per "
                "candidate feature, Peduzzi et al. 1996's logistic-regression rule of "
                "thumb). Ranking not treated as meaningful yet."
            ),
        )
    coefficients = train_logistic_regression(examples)
    importances = {k: v for k, v in coefficients.items() if k != "_intercept_"}
    return EvidenceValueReport(
        method=method, sample_size=n, feature_importances=importances, sufficient_sample=True, notes="",
    )


def rolling_window_drift(
    examples: list[TrainingExample], window_size: int, min_sample_size: int = MIN_SAMPLE_SIZE,
) -> list[EvidenceValueReport]:
    """`examples` must be chronologically ordered. Non-overlapping windows
    — each is its own independent `rank_evidence_value` call, so a window
    smaller than `min_sample_size` (the project's current real history, most
    likely) is reported "insufficient data" for that window rather than
    forcing a number out of too few decisions."""
    reports = []
    for start in range(0, len(examples), window_size):
        window = examples[start:start + window_size]
        reports.append(rank_evidence_value(
            window, min_sample_size, method=f"rolling_window[{start}:{start + len(window)}]",
        ))
    return reports


def regime_sliced_ranking(
    examples_by_regime: dict[str, list[TrainingExample]], min_sample_size: int = MIN_SAMPLE_SIZE,
) -> dict[str, EvidenceValueReport]:
    return {
        regime: rank_evidence_value(examples, min_sample_size, method=f"regime_sliced[{regime}]")
        for regime, examples in examples_by_regime.items()
    }
