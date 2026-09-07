import httpx

from app.config import Settings


class CoinGeckoClient:
    """Thin wrapper around the CoinGecko `/coins/markets` endpoint.

    Fetches all configured assets in a single request to stay well within
    free-tier rate limits, regardless of universe size.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.coingecko_base_url
        self._vs_currency = settings.vs_currency
        self._api_key = (
            settings.coingecko_api_key.get_secret_value() if settings.coingecko_api_key else None
        )

    def fetch_markets(self, coingecko_ids: list[str]) -> dict[str, dict]:
        """Returns a dict keyed by CoinGecko id -> raw market data entry."""
        if not coingecko_ids:
            return {}

        headers = {}
        if self._api_key:
            headers["x-cg-demo-api-key"] = self._api_key

        params = {
            "vs_currency": self._vs_currency,
            "ids": ",".join(coingecko_ids),
            "price_change_percentage": "24h,7d,30d",
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/coins/markets", params=params, headers=headers
            )
            response.raise_for_status()
            entries = response.json()

        return {entry["id"]: entry for entry in entries}

    def search_coin_by_symbol(self, symbol: str) -> dict | None:
        """Phase 5b: the free `/search` endpoint (no key needed) -- looks
        up a real CoinGecko-listed coin by ticker symbol, used to verify a
        user-entered holdings symbol that isn't yet in our tracked assets
        table before creating a new asset row for it (never trusting the
        typed symbol blindly). A ticker can match several real coins
        (e.g. scam/copycat tokens sharing a well-known symbol); this
        returns the one with the lowest `market_cap_rank` among exact
        (case-insensitive) ticker matches -- the real, well-known token --
        or `None` if no CoinGecko coin has this exact ticker at all."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{self._base_url}/search", params={"query": symbol})
            response.raise_for_status()
            data = response.json()

        matches = [c for c in data.get("coins", []) if c.get("symbol", "").upper() == symbol.upper()]
        if not matches:
            return None
        matches.sort(key=lambda c: (c.get("market_cap_rank") is None, c.get("market_cap_rank") or 0))
        return matches[0]

    def fetch_top_markets(self, limit: int) -> list[dict]:
        """Returns the top `limit` assets by market cap (no `ids` filter) —
        used by 3b's screening universe to discover candidates beyond the
        existing tracked assets. One batched call regardless of `limit`."""
        headers = {}
        if self._api_key:
            headers["x-cg-demo-api-key"] = self._api_key

        params = {
            "vs_currency": self._vs_currency,
            "order": "market_cap_desc",
            "per_page": limit,
            "page": 1,
            "price_change_percentage": "24h,7d,30d",
        }

        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/coins/markets", params=params, headers=headers
            )
            response.raise_for_status()
            return response.json()
