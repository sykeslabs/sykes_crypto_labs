from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.market_data.schemas import MarketSnapshot


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def normalize_coingecko_entry(asset_id: str, entry: dict) -> MarketSnapshot:
    """Maps a raw CoinGecko `/coins/markets` entry to a normalized MarketSnapshot.

    Uses CoinGecko's own `last_updated` field as the snapshot timestamp — the
    time the price data actually reflects, not the time we happened to fetch it.
    """
    price = _to_decimal(entry.get("current_price"))
    if price is None:
        raise ValueError(f"CoinGecko entry for '{entry.get('id')}' has no usable current_price")

    last_updated_raw = entry.get("last_updated")
    if last_updated_raw:
        timestamp = datetime.fromisoformat(last_updated_raw.replace("Z", "+00:00"))
    else:
        timestamp = datetime.now(UTC)

    return MarketSnapshot(
        asset_id=asset_id,
        timestamp=timestamp,
        price=price,
        market_cap=_to_decimal(entry.get("market_cap")),
        volume_24h=_to_decimal(entry.get("total_volume")),
        price_change_24h=_to_decimal(entry.get("price_change_percentage_24h_in_currency")),
        price_change_7d=_to_decimal(entry.get("price_change_percentage_7d_in_currency")),
        price_change_30d=_to_decimal(entry.get("price_change_percentage_30d_in_currency")),
        source="coingecko",
    )
