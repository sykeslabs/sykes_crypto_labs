"""Point-in-time factor reconstruction for 3e.1's replay. Reuses 3b's pure,
already-tested factor functions (`app/market_data/factors.py`,
`app/market_data/anomaly.py`) against a historical close/volume series
windowed up to a cutoff date — never anything after it. This is what makes
the replay's screening/regime inputs genuinely non-lookahead, not a
reimplementation of 3b's logic.
"""

from dataclasses import dataclass
from datetime import datetime

from app.market_data.anomaly import detect_anomaly
from app.market_data.factors import compute_max_drawdown, compute_relative_strength, compute_volatility

# How many trailing daily points volatility/drawdown/anomaly-detection need
# to be meaningful — matches 3b's OHLCV_LOOKBACK_DAYS convention.
TRAILING_WINDOW_DAYS = 31


@dataclass
class HistoricalSeries:
    """One asset's full fetched daily (date, close, volume) history, oldest
    first. `source` records which venue it came from (BINANCE/COINBASE/
    UNAVAILABLE), same convention as 3b's `volatility_drawdown_source`."""

    symbol: str
    asset_id: str
    source: str
    dates: list[datetime]
    closes: list[float]
    volumes: list[float]

    def as_of(self, cutoff: datetime) -> tuple[list[datetime], list[float], list[float]]:
        """The (dates, closes, volumes) prefix with date <= cutoff — a
        point-in-time window, never anything after `cutoff`."""
        idx = 0
        for i, d in enumerate(self.dates):
            if d <= cutoff:
                idx = i + 1
            else:
                break
        return self.dates[:idx], self.closes[:idx], self.volumes[:idx]


def pct_change(closes: list[float], lookback_days: int) -> float | None:
    """Percentage change (matching CoinGecko's percent-units convention used
    live, e.g. 5.2 meaning +5.2%) from `lookback_days` ago to the series'
    last point. None if there isn't enough history."""
    if len(closes) <= lookback_days:
        return None
    old, new = closes[-lookback_days - 1], closes[-1]
    if old == 0:
        return None
    return (new / old - 1) * 100


@dataclass
class PointInTimeFactors:
    momentum_7d: float | None
    momentum_30d: float | None
    volatility_30d: float | None
    drawdown_30d: float | None
    relative_strength_30d: float | None
    volume_24h_proxy: float | None  # close * base-asset volume — a USD-notional proxy, not exact
    anomaly_flag: bool
    anomaly_reason: str | None
    price: float | None


def compute_point_in_time_factors(
    series: HistoricalSeries, cutoff: datetime, btc_momentum_30d: float | None
) -> PointInTimeFactors:
    dates, closes, volumes = series.as_of(cutoff)
    if not closes:
        return PointInTimeFactors(None, None, None, None, None, None, False, None, None)

    trailing_closes = closes[-TRAILING_WINDOW_DAYS:]
    trailing_volumes = volumes[-TRAILING_WINDOW_DAYS:]

    momentum_30d = pct_change(closes, 30)
    anomaly_flag, anomaly_reason = (
        detect_anomaly(trailing_closes, trailing_volumes) if len(trailing_closes) >= 2 else (False, None)
    )

    return PointInTimeFactors(
        momentum_7d=pct_change(closes, 7),
        momentum_30d=momentum_30d,
        volatility_30d=compute_volatility(trailing_closes),
        drawdown_30d=compute_max_drawdown(trailing_closes),
        relative_strength_30d=compute_relative_strength(momentum_30d, btc_momentum_30d),
        volume_24h_proxy=closes[-1] * volumes[-1] if volumes else None,
        anomaly_flag=anomaly_flag,
        anomaly_reason=anomaly_reason,
        price=closes[-1],
    )
