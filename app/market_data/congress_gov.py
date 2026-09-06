import httpx

from app.config import Settings


class CongressGovClient:
    """Wrapper around congress.gov's public API — free, official, key-gated
    (verified live with a real signup key). No server-side full-text/keyword
    search on the bill-list endpoint (verified live: date-range filtering
    works, keyword filtering does not) — callers keyword-match titles
    client-side, same false-positive/false-negative risk PHASE3F_PROMPT.md
    itself calls out for this kind of extraction.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.congress_gov_base_url
        self._api_key = (
            settings.congress_gov_api_key.get_secret_value() if settings.congress_gov_api_key else None
        )

    @property
    def is_configured(self) -> bool:
        return self._api_key is not None

    def fetch_recent_bills(self, from_datetime: str, to_datetime: str, limit: int = 250) -> list[dict]:
        """`from_datetime`/`to_datetime` are ISO8601 e.g. "2026-08-01T00:00:00Z".
        Returns raw bill dicts (title, type, number, congress, latestAction,
        updateDate). Client-side keyword filtering happens one layer up."""
        if not self._api_key:
            return []
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/bill",
                params={
                    "api_key": self._api_key,
                    "limit": limit,
                    "sort": "updateDate desc",
                    "fromDateTime": from_datetime,
                    "toDateTime": to_datetime,
                    "format": "json",
                },
            )
            response.raise_for_status()
            data = response.json()
        return data.get("bills", [])
