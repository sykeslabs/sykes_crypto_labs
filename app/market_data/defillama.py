import httpx

from app.config import Settings


class DefiLlamaClient:
    """Wrapper around DefiLlama's public API (fully free, documented, no key
    required). Verified live: `/protocols` (8187 protocols, with `tvl` and
    `change_7d`/`change_1d`), `/v2/chains`, and the separate stablecoins API
    (`circulating`/`circulatingPrevDay`/`circulatingPrevWeek`/
    `circulatingPrevMonth` — directly gives 7d/30d stablecoin supply growth,
    no derived computation needed).
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.defillama_base_url
        self._stablecoins_base_url = settings.defillama_stablecoins_base_url

    def fetch_protocols(self) -> list[dict]:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(f"{self._base_url}/protocols")
            response.raise_for_status()
            return response.json()

    def find_protocol_by_symbol(self, symbol: str, protocols: list[dict] | None = None) -> dict | None:
        """Best-effort match: the protocol whose governance-token `symbol`
        matches, preferring the highest-TVL match if more than one protocol
        shares a symbol (common — e.g. multiple Uniswap version listings)."""
        protocols = protocols if protocols is not None else self.fetch_protocols()
        matches = [p for p in protocols if p.get("symbol") == symbol]
        if not matches:
            return None
        return max(matches, key=lambda p: p.get("tvl") or 0)

    def fetch_stablecoins(self) -> list[dict]:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                f"{self._stablecoins_base_url}/stablecoins", params={"includePrices": "true"}
            )
            response.raise_for_status()
            return response.json().get("peggedAssets", [])
