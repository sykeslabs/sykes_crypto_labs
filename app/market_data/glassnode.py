import httpx

from app.config import Settings


class GlassnodeClient:
    """Wrapper around Glassnode's API for on-chain valuation-cycle metrics
    (MVRV, SOPR, NUPL, LTH/STH cohorts) and BTC miner metrics.

    Requires GLASSNODE_API_KEY. Deliberately NOT subscribed to yet (see
    README "Known limitations / decisions") — these specific metrics are
    very likely behind Glassnode's paid tier, and this is a real recurring-
    dollar-cost decision left to the user, not something to assume. This
    client's shape is built and ready; endpoint URLs are per Glassnode's
    documented API but have NOT been live-verified end-to-end (confirmed
    only that the base API requires auth — a 401 — with no key available to
    go further). Verify once a key is added.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.glassnode_base_url
        self._api_key = (
            settings.glassnode_api_key.get_secret_value() if settings.glassnode_api_key else None
        )

    @property
    def is_configured(self) -> bool:
        return self._api_key is not None

    def fetch_metric(self, endpoint: str, asset: str, params: dict | None = None) -> list[dict]:
        """`endpoint` is a Glassnode metric path, e.g.
        'v1/metrics/market/mvrv' or 'v1/metrics/mining/hash_rate_mean'.
        Empty list if not configured."""
        if not self.is_configured:
            return []

        query = {"a": asset, "api_key": self._api_key, **(params or {})}
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{self._base_url}/{endpoint}", params=query)
            response.raise_for_status()
            return response.json()
