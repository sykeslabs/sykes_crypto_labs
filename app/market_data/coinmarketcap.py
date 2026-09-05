import logging

import httpx

from app.config import Settings

logger = logging.getLogger("crypto_ai_portfolio.market_data")


class CoinMarketCapClient:
    """Wrapper around CoinMarketCap's `/v1/cryptocurrency/quotes/latest`.

    Requires COINMARKETCAP_API_KEY (free tier available at
    coinmarketcap.com/api). Without one, `is_configured` is False and the
    caller is expected to record this source as NOT_IMPLEMENTED rather than
    silently skip it — never approximated.

    Endpoint URL/auth shape verified live (401 "API key missing" with the
    correct error code); response shape (quote.USD.{price,volume_24h,
    percent_change_24h/7d/30d/90d,market_cap}) is per CoinMarketCap's
    documented API and has not been live-verified end-to-end against a real
    key as of this writing — verify once a key is added.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.coinmarketcap_base_url
        self._api_key = (
            settings.coinmarketcap_api_key.get_secret_value()
            if settings.coinmarketcap_api_key
            else None
        )

    @property
    def is_configured(self) -> bool:
        return self._api_key is not None

    def fetch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Returns a dict keyed by symbol -> raw quote entry. Empty dict if
        not configured or `symbols` is empty — callers must check
        `is_configured` to distinguish "not configured" from "no matches"."""
        if not self.is_configured or not symbols:
            return {}

        headers = {"X-CMC_PRO_API_KEY": self._api_key, "Accept": "application/json"}
        params = {"symbol": ",".join(symbols), "convert": "USD"}

        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/v1/cryptocurrency/quotes/latest",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        raw = data.get("data", {})
        result: dict[str, dict] = {}
        for symbol, entry in raw.items():
            # CMC returns a list instead of a single object when multiple
            # listed cryptocurrencies share a ticker symbol — pick the
            # lowest (best) cmc_rank as the primary match rather than
            # guessing further; ambiguity here is a real, documented CMC
            # behavior, not something to silently resolve without a trace.
            if isinstance(entry, list):
                if not entry:
                    continue
                entry = min(entry, key=lambda e: e.get("cmc_rank") or float("inf"))
                logger.info("CMC symbol '%s' is ambiguous across multiple listings; using cmc_rank=%s", symbol, entry.get("cmc_rank"))
            result[symbol] = entry
        return result
