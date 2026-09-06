import httpx

from app.config import Settings


class FredClient:
    """Wrapper around FRED (Federal Reserve Economic Data)'s public API.
    Free, official, documented — verified live against all series this
    project uses (M2SL, WALCL, RRPONTSYD, SP500, DTWEXBGS, DEXKOUS).

    FRED's own historical gold-price series (GOLDAMGBD228NLBM) has been
    discontinued (verified live: "the series does not exist") — gold
    correlation instead uses PAXG (tokenized gold) via the existing Binance/
    Coinbase clients, a real live-verified price (~$4432/oz, matching within
    cents across both venues), not a new external dependency.
    """

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.fred_base_url
        self._api_key = (
            settings.fred_api_key.get_secret_value() if settings.fred_api_key else None
        )

    @property
    def is_configured(self) -> bool:
        return self._api_key is not None

    def fetch_latest_observation(self, series_id: str) -> dict | None:
        """Returns the single most recent real observation for `series_id`,
        e.g. {"date": "2026-09-02", "value": "..."} — None if unavailable."""
        if not self._api_key:
            return None
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                },
            )
            response.raise_for_status()
            data = response.json()
        observations = data.get("observations") or []
        if not observations or observations[0].get("value") == ".":
            return None
        return observations[0]

    def fetch_recent_observations(self, series_id: str, limit: int = 400) -> list[dict]:
        """Oldest-first, genuinely the MOST RECENT `limit` real observations
        for `series_id` — used for the rolling BTC-correlation window and
        actual-vs-previous macro readings. Excludes FRED's "." missing-value
        placeholder rows.

        A real bug lived here once: `sort_order=asc` + `limit` returns the
        OLDEST `limit` observations from the series' entire history (e.g.
        SP500 from 2016, DTWEXBGS from 2006), not the most recent — verified
        live when BTC-correlation against SP500/DXY silently produced zero
        shared dates. Fixed by requesting `sort_order=desc` (genuinely the
        most recent) then reversing to the oldest-first contract callers
        expect."""
        if not self._api_key:
            return []
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": limit,
                },
            )
            response.raise_for_status()
            data = response.json()
        observations = [o for o in (data.get("observations") or []) if o.get("value") != "."]
        observations.reverse()
        return observations

    def fetch_release_dates(self, release_id: int, realtime_start: str) -> list[str]:
        """Real scheduled release dates (past and future) for a FRED
        "release" (e.g. 10=Consumer Price Index, 50=Employment Situation,
        54=Personal Income and Outlays) — the forward-looking macro-event
        calendar's data source (task 5a). `realtime_start` is "YYYY-MM-DD";
        only dates >= this are meaningfully forward-looking. Verified live
        that release_id 101 ("FOMC Press Release") does NOT behave as a
        discrete meeting calendar (returns a date for every single day) —
        callers should not rely on it for FOMC dates.

        `include_release_dates_with_no_data=true` is required — without it,
        FRED silently excludes exactly the future/not-yet-published dates
        this method exists to find (verified live: omitting it returned
        `count: 0` for a real upcoming CPI release date)."""
        if not self._api_key:
            return []
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{self._base_url}/release/dates",
                params={
                    "release_id": release_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "sort_order": "asc",
                    "realtime_start": realtime_start,
                    "include_release_dates_with_no_data": "true",
                },
            )
            response.raise_for_status()
            data = response.json()
        return [d["date"] for d in data.get("release_dates", [])]
