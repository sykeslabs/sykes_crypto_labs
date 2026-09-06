"""Phase 4 task 1: order-book-aware, fee-aware fill simulation. Fills are
never mark-to-mid — every simulated fill accounts for real exchange fees
and either real order-book-depth slippage or a documented, clearly-labeled
volatility-scaled estimate, never unlimited liquidity at the top of book.

Two fill methods, each recorded on the result so later analysis can see
exactly which assumption produced a given number:
- DEPTH_WALKED: a real order-book snapshot is available — walks the book
  level-by-level (a simple multi-level walk, not a single top-of-book
  price) to compute a volume-weighted average execution price, and can
  report a genuine PARTIAL fill if the order exceeds available depth
  across the fetched levels.
- VOLATILITY_SCALED_ESTIMATE: no real depth data available (e.g. no
  historical order-book snapshot exists for a past decision — order books
  are not stored historically anywhere in this project, and exchanges
  don't serve historical depth via free APIs) — a documented ESTIMATE,
  never presented as measured.

Fee rates below are each exchange's own published, standard/base-tier
maker/taker rate (no VIP/volume discount, no native-token fee discount) —
commonly-published reference rates, not fetched from a live authenticated
fee-schedule API (this project uses no exchange account credentials, paper
only). Re-verify periodically, same convention as `llm/cost.py`'s
`PRICING_PER_1K_TOKENS`. A simulated decision-to-fill is treated as an
immediate (taker) order, not a resting limit order — the Judge/Risk Engine
pipeline produces one decision per run, not a maker-style quote.
"""

from dataclasses import dataclass
from typing import Literal

Side = Literal["BUY", "SELL"]
FillMethod = Literal["DEPTH_WALKED", "VOLATILITY_SCALED_ESTIMATE"]
Exchange = Literal["BINANCE", "COINBASE"]

TAKER_FEE_RATE_BY_EXCHANGE: dict[Exchange, float] = {
    "BINANCE": 0.001,   # 0.10%, Binance spot standard/VIP0, no BNB discount
    "COINBASE": 0.006,  # 0.60%, Coinbase Advanced Trade base tier (<$10K 30d volume)
}
MAKER_FEE_RATE_BY_EXCHANGE: dict[Exchange, float] = {
    "BINANCE": 0.001,
    "COINBASE": 0.004,
}

# A simple, commonly-used square-root market-impact functional form (real,
# order-size-relative-to-volume scaling of realized volatility) — kept
# intentionally simple and inspectable, same "simple, not a production risk
# desk's" standard 3e/3h already applied elsewhere. Not fit to this
# project's own data (no real fill-vs-slippage history exists yet to fit
# against) — a documented starting assumption, revisit once real fills
# accumulate.
VOLATILITY_SLIPPAGE_MULTIPLIER = 0.5


@dataclass
class OrderBookLevel:
    price: float
    quantity: float  # base-asset units available at this price


@dataclass
class OrderBookSnapshot:
    bids: list[OrderBookLevel]  # sorted highest-first
    asks: list[OrderBookLevel]  # sorted lowest-first
    source: Exchange


@dataclass
class FillResult:
    side: Side
    fill_method: FillMethod
    requested_usd: float
    filled_usd: float
    fully_filled: bool
    average_price: float
    top_of_book_price: float
    slippage_pct: float  # signed: positive = worse than top-of-book for this side
    fee_usd: float
    fee_rate: float
    levels_consumed: int | None = None


def walk_order_book(side: Side, order_size_usd: float, book: OrderBookSnapshot, fee_rate: float) -> FillResult:
    """A simple multi-level walk: consumes book levels in order until
    `order_size_usd` is filled or the fetched depth is exhausted. Returns a
    genuine partial fill (`fully_filled=False`, `filled_usd < requested_usd`)
    rather than assuming unlimited liquidity beyond the fetched levels."""
    levels = book.asks if side == "BUY" else book.bids
    if not levels:
        raise ValueError("empty order book side for the requested direction")
    top_of_book_price = levels[0].price

    remaining_usd = order_size_usd
    total_base_qty = 0.0
    total_usd_spent = 0.0
    levels_consumed = 0
    for level in levels:
        if remaining_usd <= 1e-9:
            break
        level_usd_capacity = level.price * level.quantity
        take_usd = min(remaining_usd, level_usd_capacity)
        take_qty = take_usd / level.price
        total_base_qty += take_qty
        total_usd_spent += take_usd
        remaining_usd -= take_usd
        levels_consumed += 1

    fully_filled = remaining_usd <= 1e-9
    average_price = (total_usd_spent / total_base_qty) if total_base_qty > 0 else top_of_book_price
    slippage_pct = (
        (average_price - top_of_book_price) / top_of_book_price if side == "BUY"
        else (top_of_book_price - average_price) / top_of_book_price
    )
    fee_usd = total_usd_spent * fee_rate

    return FillResult(
        side=side, fill_method="DEPTH_WALKED", requested_usd=order_size_usd,
        filled_usd=total_usd_spent, fully_filled=fully_filled, average_price=average_price,
        top_of_book_price=top_of_book_price, slippage_pct=slippage_pct,
        fee_usd=fee_usd, fee_rate=fee_rate, levels_consumed=levels_consumed,
    )


def round_trip_cost_pct(
    entry_volatility: float,
    entry_typical_daily_volume_usd: float,
    exit_volatility: float,
    exit_typical_daily_volume_usd: float,
    order_size_usd: float,
    fee_rate: float,
    slippage_multiplier: float = VOLATILITY_SLIPPAGE_MULTIPLIER,
) -> float:
    """Phase 4 task 2: the total round-trip drag (entry fee + entry
    slippage + exit fee + exit slippage, as a fraction) used to adjust an
    already-computed mark-to-mid `realized_return` down to a net-of-costs
    figure: `realized_return_net_of_costs = realized_return -
    round_trip_cost_pct(...)`. A documented simplification — this treats
    execution cost as a flat drag on the raw price-return figure rather
    than reconstructing a full directional position-level P&L, since
    `decision_outcomes.realized_return` itself is a directional-call
    proxy (see `scripts/calibration_baseline.py`), not a P&L series. Side
    doesn't affect the MAGNITUDE of this formula's slippage term (only its
    sign in `estimate_fill_volatility_scaled`), so both legs are computed
    with an arbitrary fixed side ("BUY") and only their `slippage_pct`/
    `fee_usd` are used."""
    entry = estimate_fill_volatility_scaled(
        "BUY", order_size_usd, 1.0, entry_volatility, entry_typical_daily_volume_usd,
        fee_rate, slippage_multiplier,
    )
    exit_ = estimate_fill_volatility_scaled(
        "BUY", order_size_usd, 1.0, exit_volatility, exit_typical_daily_volume_usd,
        fee_rate, slippage_multiplier,
    )
    return entry.fee_rate + exit_.fee_rate + entry.slippage_pct + exit_.slippage_pct


def estimate_fill_volatility_scaled(
    side: Side,
    order_size_usd: float,
    mid_price: float,
    recent_volatility: float,
    typical_daily_volume_usd: float,
    fee_rate: float,
    slippage_multiplier: float = VOLATILITY_SLIPPAGE_MULTIPLIER,
) -> FillResult:
    """Used when no real order-book snapshot is available. `recent_volatility`
    is a per-period (e.g. daily) realized-return standard deviation;
    `typical_daily_volume_usd` should be a real observed figure (e.g. from
    `market_snapshots.volume_24h`), never guessed. Slippage scales with
    volatility and the order's participation rate relative to typical
    volume — labeled `VOLATILITY_SCALED_ESTIMATE`, never treated as
    measured depth."""
    if typical_daily_volume_usd <= 0:
        raise ValueError("typical_daily_volume_usd must be positive")
    participation_rate = order_size_usd / typical_daily_volume_usd
    slippage_pct = slippage_multiplier * recent_volatility * (participation_rate ** 0.5)
    average_price = mid_price * (1 + slippage_pct) if side == "BUY" else mid_price * (1 - slippage_pct)
    fee_usd = order_size_usd * fee_rate

    return FillResult(
        side=side, fill_method="VOLATILITY_SCALED_ESTIMATE", requested_usd=order_size_usd,
        filled_usd=order_size_usd, fully_filled=True, average_price=average_price,
        top_of_book_price=mid_price, slippage_pct=slippage_pct, fee_usd=fee_usd,
        fee_rate=fee_rate, levels_consumed=None,
    )
