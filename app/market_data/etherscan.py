import logging
import time

import httpx

from app.config import Settings

logger = logging.getLogger("crypto_ai_portfolio.market_data")

# A small, well-known set of public exchange hot-wallet addresses — publicly
# documented on-chain facts (not sensitive), used only as a reference point
# for a large-transfer-count proxy. This is a narrower, more honest scope
# than a full exchange-flow product: it only counts native ETH transfers
# to/from these specific addresses, not a comprehensive reserve estimate.
KNOWN_EXCHANGE_ADDRESSES: dict[str, str] = {
    "binance_1": "0x28C6c06298d514Db089934071355E5743bf21d60",
    "coinbase_1": "0x71660c4005BA85c37ccec55d0C4493E66Fe775d3",
}

# Native-ETH transfer threshold (in ETH) above which a transfer counts as
# "large" for this proxy — chosen to filter routine activity, not a
# statistically derived figure.
LARGE_TRANSFER_THRESHOLD_ETH = 100.0


class EtherscanClient:
    """Wrapper around Etherscan's v2 API. Requires ETHERSCAN_API_KEY (free
    tier at etherscan.io/apis). Without one, `is_configured` is False and
    the caller records this source as NOT_IMPLEMENTED.

    Known limitation (documented, not solved here — see README): a raw
    large-transfer count to/from a handful of known addresses conflates
    genuine whale accumulation/distribution with routine exchange-internal
    or protocol traffic, since it has no entity-clustering behind it (the
    way Glassnode/Nansen-class platforms group multiple addresses controlled
    by the same actor). Shipped anyway per the task's own guidance, with
    this caveat recorded in `signal_sources.notes`.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.etherscan_base_url
        self._api_key = (
            settings.etherscan_api_key.get_secret_value() if settings.etherscan_api_key else None
        )

    @property
    def is_configured(self) -> bool:
        return self._api_key is not None

    def fetch_recent_transactions(self, address: str, chain_id: int = 1) -> list[dict]:
        """Returns recent native-ETH transactions for `address` (most recent
        first). Empty if not configured."""
        if not self.is_configured:
            return []

        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                self._base_url,
                params={
                    "chainid": chain_id,
                    "module": "account",
                    "action": "txlist",
                    "address": address,
                    "sort": "desc",
                    "apikey": self._api_key,
                },
            )
            response.raise_for_status()
            data = response.json()

        if data.get("status") != "1":
            logger.warning("Etherscan txlist for %s returned: %s", address, data.get("message"))
            return []
        return data.get("result", [])

    def count_large_transfers_last_24h(self) -> int | None:
        """Counts native-ETH transfers >= LARGE_TRANSFER_THRESHOLD_ETH,
        to/from any address in KNOWN_EXCHANGE_ADDRESSES, in roughly the last
        24h. None if not configured."""
        if not self.is_configured:
            return None

        cutoff = time.time() - 24 * 3600
        count = 0
        for address in KNOWN_EXCHANGE_ADDRESSES.values():
            for tx in self.fetch_recent_transactions(address):
                try:
                    tx_time = int(tx["timeStamp"])
                    value_eth = int(tx["value"]) / 1e18
                except (KeyError, ValueError):
                    continue
                if tx_time < cutoff:
                    break  # sorted desc — everything after this is also older
                if value_eth >= LARGE_TRANSFER_THRESHOLD_ETH:
                    count += 1
        return count
