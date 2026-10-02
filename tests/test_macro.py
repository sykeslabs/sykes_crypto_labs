from datetime import UTC, datetime, timedelta

from app.config.settings import Settings
from app.database.models import Asset
from app.market_data.congress_gov import CongressGovClient
from app.market_data.fred import FredClient
from app.market_data.macro_service import MacroService
from app.market_data.sec_edgar import SecEdgarClient
from app.market_data.upbit import UpbitClient

# --- Fakes -------------------------------------------------------------------


def _asset(symbol, asset_id=None):
    return Asset(
        id=asset_id or f"id-{symbol}", symbol=symbol, name=symbol, coingecko_id=symbol.lower(),
        active=True, in_asset=True, created_at=datetime.now(UTC),
    )


class FakeAssetRepo:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeEvidenceRepo:
    def __init__(self):
        self.inserted = []

    def insert_many(self, observations):
        self.inserted.extend(observations)


class FakeSignalSourceRepo:
    def __init__(self):
        self.statuses = {}
        self.notes = {}

    def update_status(self, name, status, notes=None):
        self.statuses[name] = status
        if notes is not None:
            self.notes[name] = notes


class FakeFredClient:
    def __init__(
        self, configured=True, macro_series=None, release_dates=None,
        latest_by_series=None, recent_by_series=None,
    ):
        self.is_configured = configured
        self._macro_series = macro_series or {}
        self._release_dates = release_dates or {}
        self._latest_by_series = latest_by_series or {}
        self._recent_by_series = recent_by_series or {}

    def fetch_recent_observations(self, series_id, limit=400):
        if series_id in self._macro_series:
            return self._macro_series[series_id]
        return self._recent_by_series.get(series_id, [])

    def fetch_release_dates(self, release_id, realtime_start):
        return [d for d in self._release_dates.get(release_id, []) if d >= realtime_start]

    def fetch_latest_observation(self, series_id):
        return self._latest_by_series.get(series_id)


class FakeUpbitClient:
    def __init__(self, ticker=None, raise_error=False):
        self._ticker = ticker
        self._raise = raise_error

    def fetch_ticker(self, market):
        if self._raise:
            raise RuntimeError("boom")
        return self._ticker


class FakeSecEdgarClient:
    def __init__(self, hits=None, raise_error=False):
        self._hits = hits or []
        self._raise = raise_error

    def search_full_text(self, query, forms=None, start_date=None, end_date=None):
        if self._raise:
            raise RuntimeError("boom")
        return self._hits


class FakeCongressGovClient:
    def __init__(self, bills=None, configured=True):
        self._bills = bills or []
        self.is_configured = configured

    def fetch_recent_bills(self, from_datetime, to_datetime, limit=250):
        return self._bills


class FakeBinanceClientForMacro:
    def __init__(self, series_by_symbol=None):
        self._series_by_symbol = series_by_symbol or {}

    def fetch_daily_ohlcv_with_timestamps(self, symbol, days):
        return self._series_by_symbol.get(symbol, [])


def _daily_series(n, start, price_fn):
    return [(start + timedelta(days=i), price_fn(i), 1000.0) for i in range(n)]


def _make_service(
    fred=None, upbit=None, sec_edgar=None, congress_gov=None, binance=None,
    signal_repo=None, evidence_repo=None,
):
    return MacroService(
        asset_repo=FakeAssetRepo([_asset("BTC")]),
        evidence_repo=evidence_repo or FakeEvidenceRepo(),
        signal_source_repo=signal_repo or FakeSignalSourceRepo(),
        fred_client=fred or FakeFredClient(configured=False),
        upbit_client=upbit or FakeUpbitClient(),
        sec_edgar_client=sec_edgar or FakeSecEdgarClient(),
        congress_gov_client=congress_gov or FakeCongressGovClient(configured=False),
        binance_client=binance or FakeBinanceClientForMacro(),
    )


# --- MacroService: macro observations / forward calendar / global liquidity --

def test_macro_observations_persisted_with_actual_and_previous():
    fred = FakeFredClient(
        configured=True,
        macro_series={"CPIAUCSL": [{"date": "2026-07-01", "value": "310.0"}, {"date": "2026-08-01", "value": "311.5"}]},
    )
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(fred=fred, evidence_repo=evidence_repo)

    result = service.run("RUN-1")

    assert "cpi" in result.macro_observations
    cpi_obs = next(o for o in evidence_repo.inserted if o.source == "macro_cpi")
    assert cpi_obs.payload["actual"] == "311.5"
    assert cpi_obs.payload["previous"] == "310.0"
    assert cpi_obs.payload["consensus"] is None  # no free consensus source found — never fabricated


def test_macro_observations_not_implemented_without_fred_key():
    service = _make_service(fred=FakeFredClient(configured=False))
    result = service.run("RUN-1")
    assert result.macro_observations == []
    assert result.source_status["Macro"] == "NOT_IMPLEMENTED"


def test_forward_calendar_only_includes_future_dates_within_horizon():
    # Dates computed relative to the real clock (service.run() uses
    # datetime.now(UTC) internally, not injectable) -- a hardcoded date
    # eventually becomes "past" as real calendar time passes, which is
    # exactly the false failure this once produced. FORWARD_CALENDAR_
    # HORIZON_DAYS is 120 (app/market_data/macro_service.py); the filter is
    # inclusive (today <= d <= horizon), so +30d/-30d/+200d are all safely
    # on one side of each boundary.
    today = datetime.now(UTC).date()
    past_date = (today - timedelta(days=30)).isoformat()
    within_horizon_date = (today + timedelta(days=30)).isoformat()
    beyond_horizon_date = (today + timedelta(days=200)).isoformat()
    fred = FakeFredClient(configured=True, release_dates={10: [past_date, within_horizon_date, beyond_horizon_date]})
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(fred=fred, evidence_repo=evidence_repo)

    service.run("RUN-1")

    calendar_entries = [o for o in evidence_repo.inserted if o.source == "scheduled_macro_event"]
    dates = {o.payload["scheduled_date"] for o in calendar_entries}
    assert within_horizon_date in dates
    assert past_date not in dates  # past
    assert beyond_horizon_date not in dates  # beyond the horizon


def test_global_liquidity_series_persisted():
    fred = FakeFredClient(
        configured=True,
        latest_by_series={"M2SL": {"date": "2026-08-01", "value": "21900"}},
    )
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(fred=fred, evidence_repo=evidence_repo)

    result = service.run("RUN-1")

    assert "m2" in result.global_liquidity_series
    m2_obs = next(o for o in evidence_repo.inserted if o.source == "global_liquidity_m2")
    assert m2_obs.scope == "GLOBAL_CRYPTO"


# --- MacroService: correlation ------------------------------------------------

def test_correlation_computed_with_enough_shared_dates():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    n = 150
    btc_series = _daily_series(n, start, lambda i: 100.0 * (1.01**i))
    paxg_series = _daily_series(n, start, lambda i: 2000.0 * (1.002**i))
    binance = FakeBinanceClientForMacro(series_by_symbol={"BTC": btc_series, "PAXG": paxg_series})

    evidence_repo = FakeEvidenceRepo()
    service = _make_service(fred=FakeFredClient(configured=False), binance=binance, evidence_repo=evidence_repo)
    result = service.run("RUN-1")

    assert "gold_paxg" in result.correlations_computed
    corr_obs = next(o for o in evidence_repo.inserted if o.source == "btc_correlation_gold_paxg")
    assert "30d" in corr_obs.payload["windows"]
    assert "90d" in corr_obs.payload["windows"]


def test_correlation_skipped_with_insufficient_shared_dates():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    btc_series = _daily_series(50, start, lambda i: 100.0 + i)  # too short for the 90d window
    binance = FakeBinanceClientForMacro(series_by_symbol={"BTC": btc_series, "PAXG": btc_series})

    service = _make_service(fred=FakeFredClient(configured=False), binance=binance)
    result = service.run("RUN-1")

    assert "gold_paxg" not in result.correlations_computed


# --- MacroService: regional premium --------------------------------------------

def test_regional_premium_computed_from_real_shaped_inputs():
    fred = FakeFredClient(configured=True, latest_by_series={"DEXKOUS": {"date": "2026-09-05", "value": "1400.0"}})
    upbit = FakeUpbitClient(ticker={"trade_price": 145000000.0})
    start = datetime(2026, 1, 1, tzinfo=UTC)
    btc_series = _daily_series(5, start, lambda i: 100000.0)
    binance = FakeBinanceClientForMacro(series_by_symbol={"BTC": btc_series})

    evidence_repo = FakeEvidenceRepo()
    service = _make_service(fred=fred, upbit=upbit, binance=binance, evidence_repo=evidence_repo)
    result = service.run("RUN-1")

    assert result.regional_premium_computed is True
    premium_obs = next(o for o in evidence_repo.inserted if o.source == "regional_exchange_premium_upbit")
    # implied_usd = 145,000,000 / 1400 ~= 103,571 vs global 100,000 -> positive premium
    assert premium_obs.payload["premium_pct"] > 0


def test_regional_premium_unavailable_when_upbit_fails():
    service = _make_service(upbit=FakeUpbitClient(raise_error=True))
    result = service.run("RUN-1")
    assert result.regional_premium_computed is False
    assert result.source_status["REGIONAL_EXCHANGE_PREMIUM"] == "UNAVAILABLE"


# --- MacroService: regulatory calendar -----------------------------------------

def test_regulatory_events_from_sec_edgar_and_congress_keyword_filtered():
    sec_edgar = FakeSecEdgarClient(hits=[
        {"form": "8-K", "display_names": ["Nakamoto Inc."], "file_date": "2026-08-14", "adsh": "123"},
    ])
    congress = FakeCongressGovClient(configured=True, bills=[
        {"title": "A bill about digital asset regulation", "type": "HR", "number": "1", "congress": 119,
         "updateDate": "2026-08-20", "latestAction": {}},
        {"title": "A bill about postal facilities", "type": "HR", "number": "2", "congress": 119,
         "updateDate": "2026-08-21", "latestAction": {}},
    ])
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(sec_edgar=sec_edgar, congress_gov=congress, evidence_repo=evidence_repo)

    result = service.run("RUN-1")

    assert result.regulatory_events_found == 2  # 1 SEC hit + 1 keyword-matched bill (postal one excluded)
    sources = {o.source for o in evidence_repo.inserted}
    assert "regulatory_event_sec_edgar" in sources
    assert "regulatory_event_congress" in sources
    assert result.source_status["REGULATORY_EVENT_CALENDAR"] == "OK"


def test_regulatory_calendar_unavailable_when_both_sources_fail():
    service = _make_service(
        sec_edgar=FakeSecEdgarClient(raise_error=True),
        congress_gov=FakeCongressGovClient(configured=False),
    )
    result = service.run("RUN-1")
    assert result.source_status["REGULATORY_EVENT_CALENDAR"] == "UNAVAILABLE"


# --- MacroService: every deferred source reaffirmed every run -----------------

def test_all_deferred_sources_reaffirmed_with_real_notes_every_run():
    # Regression test for the exact gap a 3c live-verification incident
    # caught: a signal_sources status never actually re-checked by code
    # looks identical, in a clean report, to one genuinely reaffirmed.
    signal_repo = FakeSignalSourceRepo()
    service = _make_service(signal_repo=signal_repo)

    service.run("RUN-1")

    for name in ("CryptoBubbles", "CoinAnk", "CoinGlass", "PlanB", "SOCIAL_NARRATIVE_SENTIMENT"):
        assert name in signal_repo.statuses, name
        assert name in signal_repo.notes, name
        assert len(signal_repo.notes[name]) > 20


# --- FredClient regression tests (real bugs found live) -----------------------

class FakeHttpResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fred_fetch_recent_observations_uses_desc_then_reverses(monkeypatch):
    # Regression: sort_order=asc + limit returns the OLDEST N observations
    # from series inception, not the most recent N — verified live when
    # BTC-correlation against SP500/DXY silently produced zero shared dates.
    captured_params = {}

    def fake_get(self, url, params=None):
        captured_params.update(params)
        return FakeHttpResponse({"observations": [
            {"date": "2026-09-05", "value": "100"}, {"date": "2026-09-04", "value": "99"},
        ]})

    monkeypatch.setattr("httpx.Client.get", fake_get)
    settings = Settings(_env_file=None, fred_api_key="key")
    client = FredClient(settings)

    result = client.fetch_recent_observations("SP500", limit=2)

    assert captured_params["sort_order"] == "desc"
    assert [o["date"] for o in result] == ["2026-09-04", "2026-09-05"]  # reversed to oldest-first


def test_fred_fetch_release_dates_includes_no_data_flag(monkeypatch):
    # Regression: omitting include_release_dates_with_no_data=true silently
    # excludes future/not-yet-published release dates — verified live
    # (count: 0 for a real, known upcoming CPI release date).
    captured_params = {}

    def fake_get(self, url, params=None):
        captured_params.update(params)
        return FakeHttpResponse({"release_dates": [{"release_id": 10, "date": "2026-10-01"}]})

    monkeypatch.setattr("httpx.Client.get", fake_get)
    settings = Settings(_env_file=None, fred_api_key="key")
    client = FredClient(settings)

    client.fetch_release_dates(10, realtime_start="2026-09-01")

    assert captured_params["include_release_dates_with_no_data"] == "true"


def test_fred_client_not_configured_returns_empty():
    settings = Settings(_env_file=None)
    client = FredClient(settings)
    assert client.is_configured is False
    assert client.fetch_recent_observations("SP500") == []
    assert client.fetch_latest_observation("SP500") is None
    assert client.fetch_release_dates(10, "2026-01-01") == []


# --- Basic client tests (Upbit / SEC EDGAR / congress.gov) --------------------

def test_upbit_client_parses_first_ticker(monkeypatch):
    def fake_get(self, url, params=None):
        return FakeHttpResponse([{"market": "KRW-BTC", "trade_price": 145000000.0}])

    monkeypatch.setattr("httpx.Client.get", fake_get)
    settings = Settings(_env_file=None)
    client = UpbitClient(settings)
    ticker = client.fetch_ticker("KRW-BTC")
    assert ticker["trade_price"] == 145000000.0


def test_sec_edgar_client_extracts_hits(monkeypatch):
    def fake_get(self, url, params=None):
        return FakeHttpResponse({"hits": {"hits": [{"_source": {"form": "8-K"}}]}})

    monkeypatch.setattr("httpx.Client.get", fake_get)
    settings = Settings(_env_file=None)
    client = SecEdgarClient(settings)
    hits = client.search_full_text("bitcoin")
    assert hits == [{"form": "8-K"}]


def test_congress_gov_client_not_configured_returns_empty():
    settings = Settings(_env_file=None)
    client = CongressGovClient(settings)
    assert client.is_configured is False
    assert client.fetch_recent_bills("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z") == []
