"""Phase 3h task 2: deterministic, non-LLM portfolio tail-risk stress
testing. Reporting-only — flags a candidate/current allocation whose
estimated stress-scenario drawdown exceeds a configurable threshold, same
standing as `requires_review` from 3e (never blocks Portfolio Construction).
Runnable ad hoc against the current portfolio, or against any historical/
candidate allocation dict — this module takes allocations as a plain
argument rather than reading `portfolio_positions` itself, so a caller can
pass any point-in-time snapshot.

Two scenario templates (kept simple/inspectable per the task's own
instruction, not a production risk desk's VaR engine):

1. HISTORICAL_WORST_DRAWDOWN — each asset's own REAL historical peak-to-
   trough drawdown, computed by the caller from real fetched exchange OHLCV
   (see scripts/run_stress_test.py, which now pages Binance's client past
   its real 1000-candle-per-call cap) and passed in as `AssetDrawdownInput`.
   This single scenario satisfies both the task's "broad ~70% BTC drawdown,
   2022-style" example AND its "at least one scenario using actual
   historical returns" requirement — with pagination, BTC's real reachable
   history now goes back to its actual 2017-08-17 Binance listing date
   (live-verified), covering both the 2022 cycle and the even deeper
   2017-2018 crash (-83.2%, Dec 2017 to Dec 2018 — the real worst drawdown
   in that window, not a "2022-style" figure specifically). Previously this
   capped out at ~2.7 reachable years and missed both; see README for the
   incident and fix.
2. ALTCOIN_CONTAGION_LUNA_FTX_STYLE — a stated scenario ASSUMPTION (not
   fitted from data): correlations move toward 1, majors and everything else
   assigned different fixed drawdown percentages.

Each scenario's "CVaR-style estimate" is deliberately identical to its
portfolio drawdown: with a single deterministic scenario (not a return
distribution), expected-loss-beyond-a-threshold reduces exactly to that
scenario's own loss — a real simplification, disclosed rather than dressed
up as a full historical VaR/CVaR computation.
"""

from dataclasses import dataclass, field

# Contagion-scenario assumption tiers — a stated modeling assumption, not
# fitted from data. Majors assumed to fall less than alts in a correlated-
# crash/contagion event; broadly consistent with (though not derived from)
# this project's own real HISTORICAL_WORST_DRAWDOWN numbers, where every
# real alt drawdown was meaningfully deeper than BTC's/ETH's (see README).
CONTAGION_MAJOR_DRAWDOWN = -0.50
CONTAGION_ALT_DRAWDOWN = -0.85
CONTAGION_MAJORS = frozenset({"BTC", "ETH"})

# A symbol with no real historical data at all (or none this module trusts)
# falls back to this symbol's own real computed drawdown as a documented
# proxy — the "apply the BTC/large-cap-alt historical drawdown percentage to
# the smaller-cap asset" allowance the task explicitly names.
FALLBACK_PROXY_SYMBOL = "BTC"


@dataclass
class AssetDrawdownInput:
    """One asset's real historical drawdown input, as computed by the
    caller from real fetched OHLCV (see scripts/run_stress_test.py) — this
    module does no fetching itself, keeping it pure and unit-testable."""

    symbol: str
    max_drawdown: float | None  # None if genuinely no real data exists
    is_stale: bool = False  # real data exists but its end date doesn't reach near "now"
    data_points: int = 0
    start_date: str | None = None
    end_date: str | None = None


@dataclass
class ScenarioAssetResult:
    symbol: str
    drawdown_pct: float
    is_proxy: bool
    proxy_reason: str | None = None


@dataclass
class ScenarioResult:
    scenario_name: str
    description: str
    asset_results: list[ScenarioAssetResult] = field(default_factory=list)
    portfolio_drawdown_pct: float = 0.0  # negative
    cvar_style_estimate_pct: float = 0.0  # see module docstring's simplification note
    flagged: bool = False


def historical_worst_drawdown_scenario(
    allocations: dict[str, float],
    drawdown_inputs: dict[str, AssetDrawdownInput],
    max_stress_scenario_drawdown: float,
) -> ScenarioResult:
    fallback = drawdown_inputs.get(FALLBACK_PROXY_SYMBOL)
    fallback_drawdown = fallback.max_drawdown if fallback and fallback.max_drawdown is not None else 0.0

    asset_results = []
    portfolio_drawdown = 0.0
    for symbol, weight in allocations.items():
        entry = drawdown_inputs.get(symbol)
        if entry is None or entry.max_drawdown is None:
            drawdown = fallback_drawdown
            is_proxy = True
            reason = (
                f"no real historical data available for {symbol}; using "
                f"{FALLBACK_PROXY_SYMBOL}'s real computed drawdown "
                f"({fallback_drawdown:.1%}) as a documented proxy"
            )
        else:
            drawdown = entry.max_drawdown
            is_proxy = False
            reason = (
                f"real historical data, but stale — window ends {entry.end_date}, "
                "not near the current date; reflects an outdated volatility regime"
                if entry.is_stale else None
            )
        asset_results.append(ScenarioAssetResult(
            symbol=symbol, drawdown_pct=drawdown, is_proxy=is_proxy, proxy_reason=reason,
        ))
        portfolio_drawdown += weight * drawdown

    return ScenarioResult(
        scenario_name="HISTORICAL_WORST_DRAWDOWN",
        description=(
            "Each asset's own real historical peak-to-trough drawdown, computed "
            "from real fetched exchange OHLCV (Binance primary, paginated back "
            "to its own real listing date; Coinbase fallback, unpaginated, for "
            "symbols with no Binance pair) over whatever real window is "
            "available. Assets with no real data (or only stale data) use "
            f"{FALLBACK_PROXY_SYMBOL}'s own real drawdown as a documented proxy."
        ),
        asset_results=asset_results,
        portfolio_drawdown_pct=portfolio_drawdown,
        cvar_style_estimate_pct=portfolio_drawdown,
        flagged=abs(portfolio_drawdown) > max_stress_scenario_drawdown,
    )


def altcoin_contagion_scenario(
    allocations: dict[str, float],
    max_stress_scenario_drawdown: float,
) -> ScenarioResult:
    asset_results = []
    portfolio_drawdown = 0.0
    for symbol, weight in allocations.items():
        drawdown = CONTAGION_MAJOR_DRAWDOWN if symbol in CONTAGION_MAJORS else CONTAGION_ALT_DRAWDOWN
        asset_results.append(ScenarioAssetResult(symbol=symbol, drawdown_pct=drawdown, is_proxy=False))
        portfolio_drawdown += weight * drawdown

    return ScenarioResult(
        scenario_name="ALTCOIN_CONTAGION_LUNA_FTX_STYLE",
        description=(
            "A stated scenario ASSUMPTION, not fitted from data: correlations "
            "move toward 1 in a contagion-style event; majors (BTC/ETH) assumed "
            f"to fall {CONTAGION_MAJOR_DRAWDOWN:.0%}, every other asset assumed "
            f"to fall {CONTAGION_ALT_DRAWDOWN:.0%}."
        ),
        asset_results=asset_results,
        portfolio_drawdown_pct=portfolio_drawdown,
        cvar_style_estimate_pct=portfolio_drawdown,
        flagged=abs(portfolio_drawdown) > max_stress_scenario_drawdown,
    )


def run_all_scenarios(
    allocations: dict[str, float],
    drawdown_inputs: dict[str, AssetDrawdownInput],
    max_stress_scenario_drawdown: float,
) -> list[ScenarioResult]:
    return [
        historical_worst_drawdown_scenario(allocations, drawdown_inputs, max_stress_scenario_drawdown),
        altcoin_contagion_scenario(allocations, max_stress_scenario_drawdown),
    ]
