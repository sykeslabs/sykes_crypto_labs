"""Pure, deterministic correlation math for the Risk Engine's
correlation-awareness check (task 2) — no network calls, backtestable
against any stored `market_snapshots` history.
"""


def compute_daily_returns(daily_closes: list[float]) -> list[float]:
    """Oldest-first close series -> oldest-first day-over-day returns."""
    return [
        (daily_closes[i] / daily_closes[i - 1]) - 1
        for i in range(1, len(daily_closes))
        if daily_closes[i - 1] != 0
    ]


def pearson_correlation(a: list[float], b: list[float]) -> float | None:
    """Pearson correlation over the trailing min(len(a), len(b)) points of
    each series. None if fewer than 2 overlapping points, or if either
    series has zero variance (a flat/constant series has no defined
    correlation)."""
    n = min(len(a), len(b))
    if n < 2:
        return None
    a, b = a[-n:], b[-n:]
    mean_a, mean_b = sum(a) / n, sum(b) / n
    covariance = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    variance_a = sum((x - mean_a) ** 2 for x in a)
    variance_b = sum((x - mean_b) ** 2 for x in b)
    if variance_a == 0 or variance_b == 0:
        return None
    return covariance / (variance_a**0.5 * variance_b**0.5)


def compute_correlation_matrix(returns_by_symbol: dict[str, list[float]]) -> dict[tuple[str, str], float]:
    """All pairwise correlations among the given symbols' return series.
    Missing/undefined pairs (per `pearson_correlation`) are simply absent
    from the result, not zeroed."""
    symbols = sorted(returns_by_symbol)
    matrix: dict[tuple[str, str], float] = {}
    for i, symbol_a in enumerate(symbols):
        for symbol_b in symbols[i + 1:]:
            corr = pearson_correlation(returns_by_symbol[symbol_a], returns_by_symbol[symbol_b])
            if corr is not None:
                matrix[(symbol_a, symbol_b)] = corr
    return matrix


def flag_concentrated_pairs(
    matrix: dict[tuple[str, str], float], threshold: float
) -> list[tuple[str, str, float]]:
    """Pairs at/above `threshold` — a flag, not a block (per task 2: "flag
    (don't necessarily block)")."""
    return [(a, b, corr) for (a, b), corr in matrix.items() if corr >= threshold]
