from datetime import datetime

from pydantic import BaseModel


class ScreenedAsset(BaseModel):
    """One row of `screened_universe` — a screened asset's factors for one
    run, whether or not it became a TOP_CANDIDATE. `asset_id` is only set
    once/if this symbol corresponds to an existing `assets` row."""

    id: str | None = None
    run_id: str
    computed_at: datetime
    symbol: str
    coingecko_id: str | None = None
    coinmarketcap_id: str | None = None
    asset_id: str | None = None
    rank: int | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    momentum_7d: float | None = None
    momentum_30d: float | None = None
    volatility_30d: float | None = None
    drawdown_30d: float | None = None
    volatility_drawdown_source: str | None = None  # BINANCE / COINBASE / UNAVAILABLE
    relative_strength_30d: float | None = None
    composite_factor_score: float | None = None
    anomaly_flag: bool = False
    anomaly_reason: str | None = None
    is_top_candidate: bool = False
    source_prices: dict = {}

    def to_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "computed_at": self.computed_at.isoformat(),
            "symbol": self.symbol,
            "coingecko_id": self.coingecko_id,
            "coinmarketcap_id": self.coinmarketcap_id,
            "asset_id": self.asset_id,
            "rank": self.rank,
            "market_cap": self.market_cap,
            "volume_24h": self.volume_24h,
            "momentum_7d": self.momentum_7d,
            "momentum_30d": self.momentum_30d,
            "volatility_30d": self.volatility_30d,
            "drawdown_30d": self.drawdown_30d,
            "volatility_drawdown_source": self.volatility_drawdown_source,
            "relative_strength_30d": self.relative_strength_30d,
            "composite_factor_score": self.composite_factor_score,
            "anomaly_flag": self.anomaly_flag,
            "anomaly_reason": self.anomaly_reason,
            "is_top_candidate": self.is_top_candidate,
            "source_prices": self.source_prices,
        }


class MarketRegimeSnapshot(BaseModel):
    """One row of `market_regime_snapshots` — the run-level regime label
    every downstream stage (3d, 3e) reads instead of inferring its own."""

    id: str | None = None
    run_id: str
    computed_at: datetime
    regime: str | None = None
    inputs: dict = {}
    notes: str | None = None

    def to_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "computed_at": self.computed_at.isoformat(),
            "regime": self.regime,
            "inputs": self.inputs,
            "notes": self.notes,
        }
