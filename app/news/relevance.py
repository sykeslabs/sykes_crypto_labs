import re

from app.database.models import Asset

# Symbols shorter than this are never matched on their own — a 1-2 character
# ticker (e.g. Sonic's "S") produces far too many false positives as a plain
# word/substring match. Those assets rely on their full name matching instead.
MIN_SYMBOL_LENGTH_FOR_MATCH = 3


def match_assets(text: str, assets: list[Asset]) -> list[str]:
    """Returns the symbols of assets mentioned in `text`, matched by full
    asset name (case-insensitive) or ticker symbol (case-sensitive), both
    word-bounded.

    This is a simple keyword heuristic, not NLP — it will occasionally miss
    context (e.g. "Sonic" the token vs. unrelated uses of the word) or match
    coincidental substrings. Good enough for a cheap relevance filter feeding
    an LLM that can apply its own judgment; not a source of ground truth.

    Symbol matching is case-sensitive (exact uppercase ticker, e.g. "LINK")
    rather than case-insensitive: crypto news conventionally writes tickers
    in caps, and several tickers (LINK, BONK) are also ordinary lowercase
    English words — case-sensitivity avoids matching those as prose.
    """
    lower_text = text.lower()
    matched: list[str] = []

    for asset in assets:
        name_hit = _word_boundary_search(asset.name.lower(), lower_text)
        symbol_hit = (
            len(asset.symbol) >= MIN_SYMBOL_LENGTH_FOR_MATCH
            and _word_boundary_search(asset.symbol, text)
        )
        if name_hit or symbol_hit:
            matched.append(asset.symbol)

    return matched


def _word_boundary_search(needle: str, haystack: str) -> bool:
    pattern = rf"\b{re.escape(needle)}\b"
    return re.search(pattern, haystack) is not None
