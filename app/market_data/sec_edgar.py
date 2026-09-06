import httpx

from app.config import Settings


class SecEdgarClient:
    """Wrapper around SEC EDGAR's full-text search API — free, official,
    no key required (just a descriptive User-Agent per SEC's fair-access
    policy). Verified live: real 8-K filing hits for a "bitcoin" query.

    Per PHASE3F_PROMPT.md's own framing: the raw search access here is
    solid and official; what's genuinely unverified is *extraction* —
    reliably turning a hit into a dated, asset-specific event without an
    unacceptable false-positive rate. This client only exposes the raw
    search; asset attribution happens one layer up (see macro_service.py).
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.sec_edgar_base_url
        self._user_agent = settings.sec_edgar_user_agent

    def search_full_text(
        self, query: str, forms: str | None = None, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        """`start_date`/`end_date` are "YYYY-MM-DD". Returns raw hit
        `_source` dicts (display_names, form, file_date, adsh, etc.)."""
        params: dict = {"q": query}
        if forms:
            params["forms"] = forms
        if start_date and end_date:
            params["dateRange"] = "custom"
            params["startdt"] = start_date
            params["enddt"] = end_date

        with httpx.Client(timeout=15.0, headers={"User-Agent": self._user_agent}) as client:
            response = client.get(f"{self._base_url}/search-index", params=params)
            response.raise_for_status()
            data = response.json()

        return [hit["_source"] for hit in data.get("hits", {}).get("hits", [])]
