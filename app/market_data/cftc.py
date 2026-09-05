import httpx

from app.config import Settings

# CFTC's "Traders in Financial Futures" (TFF) report Socrata dataset —
# verified live: covers CME BITCOIN futures directly, and Ether under
# "MICRO ETHER"/"NANO ETHER" contract names (not a plain "ETHEREUM" name).
# Categorizes by Dealer, Asset Manager, Leveraged Money, Other Reportables —
# exactly the trader-category breakdown this sub-phase needs. Free, no key.
TFF_DATASET_PATH = "/resource/gpe5-46if.json"

CONTRACT_NAMES = {
    "BTC": "BITCOIN",
    "ETH": "MICRO ETHER",
}


class CftcClient:
    """Wrapper around the CFTC's public Socrata API for the weekly
    Commitment of Traders (Traders in Financial Futures) report. Verified
    live for both BTC and ETH. Published Fridays, reflecting the prior
    Tuesday's close — inherently several days stale by design, not a
    collector bug (see `decay_half_life_hours` in the caller)."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.cftc_base_url

    def fetch_latest_report(self, symbol: str) -> dict | None:
        contract_name = CONTRACT_NAMES.get(symbol)
        if not contract_name:
            return None

        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                f"{self._base_url}{TFF_DATASET_PATH}",
                params={
                    "contract_market_name": contract_name,
                    "$order": "report_date_as_yyyy_mm_dd DESC",
                    "$limit": 1,
                },
            )
            response.raise_for_status()
            rows = response.json()

        return rows[0] if rows else None
