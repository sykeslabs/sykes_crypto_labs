import httpx

from app.config import Settings


class DeribitClient:
    """Wrapper around Deribit's public API (no key required for market
    data). The dominant BTC/ETH options venue.

    Verified live: options instruments exist ONLY for BTC (978) and ETH
    (850) among every currently tracked asset — SOL, XRP, BNB, LINK, HYPE,
    DOGE, NEAR all show zero option instruments despite listing on Deribit
    for other products. Dated (non-perpetual) futures are equally BTC/ETH-only
    (verified against get_instruments — every other currency has zero dated
    futures). This client is therefore only ever called for BTC/ETH.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.deribit_base_url

    def list_option_instruments(self, currency: str) -> list[dict]:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/public/get_instruments",
                params={"currency": currency, "kind": "option", "expired": "false"},
            )
            response.raise_for_status()
            return response.json().get("result", [])

    def fetch_ticker(self, instrument_name: str) -> dict | None:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/public/ticker", params={"instrument_name": instrument_name}
            )
            data = response.json()
            if data.get("error"):
                return None
            return data.get("result")

    def find_near_atm_option(self, currency: str, spot_price: float) -> dict | None:
        """Finds the call option at the nearest upcoming expiry whose strike
        is closest to `spot_price` — an "at-the-money, near-dated" pick, per
        the task's own wording. None if no options exist for this currency."""
        options = self.list_option_instruments(currency)
        if not options:
            return None

        nearest_expiry = min(o["expiration_timestamp"] for o in options)
        calls_at_nearest = [
            o for o in options
            if o["expiration_timestamp"] == nearest_expiry and o["option_type"] == "call"
        ]
        if not calls_at_nearest:
            return None
        return min(calls_at_nearest, key=lambda o: abs(o["strike"] - spot_price))

    def fetch_futures_open_interest(self, currency: str) -> dict[str, float]:
        """Returns {instrument_name: open_interest} for every future
        (perpetual + dated) on this currency."""
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/public/get_book_summary_by_currency",
                params={"currency": currency, "kind": "future"},
            )
            response.raise_for_status()
            rows = response.json().get("result", [])
        return {row["instrument_name"]: row["open_interest"] for row in rows}

    def fetch_options_put_call_oi_ratio(self, currency: str) -> float | None:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/public/get_book_summary_by_currency",
                params={"currency": currency, "kind": "option"},
            )
            response.raise_for_status()
            rows = response.json().get("result", [])

        call_oi = sum(r["open_interest"] for r in rows if r["instrument_name"].endswith("-C"))
        put_oi = sum(r["open_interest"] for r in rows if r["instrument_name"].endswith("-P"))
        if call_oi <= 0:
            return None
        return put_oi / call_oi

    def list_dated_futures(self, currency: str) -> list[dict]:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/public/get_instruments",
                params={"currency": currency, "kind": "future", "expired": "false"},
            )
            response.raise_for_status()
            futures = response.json().get("result", [])
        return [f for f in futures if f["instrument_name"] != f"{currency}-PERPETUAL"]
