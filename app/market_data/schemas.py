from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class MarketSnapshot(BaseModel):
    """A normalized point-in-time market data snapshot for one asset.

    `id` is None until the row has been persisted and Supabase assigns one.
    """

    id: str | None = None
    asset_id: str
    timestamp: datetime
    price: Decimal
    market_cap: Decimal | None
    volume_24h: Decimal | None
    price_change_24h: Decimal | None
    price_change_7d: Decimal | None
    price_change_30d: Decimal | None
    source: str = "coingecko"

    def to_row(self) -> dict:
        """Serialize for insertion via the Supabase REST client (JSON-safe)."""
        return {
            "asset_id": self.asset_id,
            "timestamp": self.timestamp.isoformat(),
            "price": str(self.price),
            "market_cap": str(self.market_cap) if self.market_cap is not None else None,
            "volume_24h": str(self.volume_24h) if self.volume_24h is not None else None,
            "price_change_24h": str(self.price_change_24h) if self.price_change_24h is not None else None,
            "price_change_7d": str(self.price_change_7d) if self.price_change_7d is not None else None,
            "price_change_30d": str(self.price_change_30d) if self.price_change_30d is not None else None,
            "source": self.source,
        }
