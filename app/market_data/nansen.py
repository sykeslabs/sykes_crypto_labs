import logging

import httpx

from app.config import Settings

logger = logging.getLogger("crypto_ai_portfolio.market_data")

# Verified live against Nansen's real docs (docs.nansen.ai/api/smart-money/
# netflows) — the smart-money endpoints only cover this fixed set of chains,
# NOT all chains Nansen indexes generally. Bitcoin is not among them — a
# real, disclosed coverage gap (see README's Phase 3i section), not an
# oversight.
SMART_MONEY_CHAINS: frozenset[str] = frozenset({
    "arbitrum", "avalanche", "base", "bnb", "ethereum", "hyperevm", "iotaevm",
    "linea", "mantle", "monad", "optimism", "plasma", "polygon", "robinhood",
    "sei", "solana", "sonic",
})


class NansenClient:
    """Wrapper around Nansen's smart-money netflow API. Requires
    NANSEN_API_KEY (free tier at nansen.ai — 100 one-time credits + 10/day
    refill, all endpoints available, real but genuinely credit-constrained).
    Without a key, `is_configured` is False and the caller records this
    source as NOT_IMPLEMENTED.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.nansen_base_url
        self._api_key = (
            settings.nansen_api_key.get_secret_value() if settings.nansen_api_key else None
        )

    @property
    def is_configured(self) -> bool:
        return self._api_key is not None

    def fetch_smart_money_netflow(self, chain: str, per_page: int = 100) -> list[dict] | None:
        """One call covers an entire chain's tracked smart-money-active
        tokens (not one call per asset) — far more credit-efficient than a
        per-asset query, and avoids needing to independently know/verify
        each asset's exact contract address (callers match by the
        `token_symbol` Nansen itself returns, never a guessed address).
        Returns None on failure (never fabricated data); an empty list is a
        genuine "no tracked smart-money activity" result, distinct from
        "not configured"/"call failed"."""
        if not self.is_configured:
            return None

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    f"{self._base_url}/smart-money/netflow",
                    headers={"Content-Type": "application/json", "apikey": self._api_key},
                    json={
                        "chains": [chain],
                        "pagination": {"page": 1, "per_page": per_page},
                        "order_by": [{"field": "net_flow_7d_usd", "direction": "DESC"}],
                    },
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Nansen smart-money netflow failed for chain=%s: %s", chain, exc)
            return None

        return data.get("data", [])
