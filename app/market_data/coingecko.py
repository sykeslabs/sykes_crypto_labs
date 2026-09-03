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
