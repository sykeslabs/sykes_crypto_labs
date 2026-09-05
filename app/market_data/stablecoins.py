"""A documented denylist, not an API call: excluding stablecoins from the
screening universe (they're never a sensible BUY/SELL candidate for this
system) and from the altcoin-season calculation (which is explicitly
defined over non-stablecoin assets) doesn't need live categorization data —
a small, maintained symbol list is simpler and has zero extra API cost.
"""

STABLECOIN_SYMBOLS: set[str] = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDE", "USDP", "FDUSD",
    "PYUSD", "GUSD", "FRAX", "LUSD", "USDD", "EURS", "USTC", "USDS",
}


def is_stablecoin(symbol: str) -> bool:
    return symbol.upper() in STABLECOIN_SYMBOLS
