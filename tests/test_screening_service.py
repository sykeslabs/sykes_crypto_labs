from datetime import UTC, datetime

from app.config.settings import Settings
from app.database.models import Asset
from app.market_data.screening_service import ScreeningService

# --- Fakes -------------------------------------------------------------------


class FakeAssetRepository:
    def __init__(self, existing_by_coingecko_id=None):
        self._existing = existing_by_coingecko_id or {}
        self.created = []

    def get_by_coingecko_id(self, coingecko_id):
        return self._existing.get(coingecko_id)

    def create_asset(self, symbol, name, coingecko_id, coinmarketcap_id=None, active=True, in_asset=False):
        asset = Asset(
            id=f"new-{symbol}", symbol=symbol, name=name, coingecko_id=coingecko_id,
            coinmarketcap_id=coinmarketcap_id, active=active, in_asset=in_asset,
            created_at=datetime.now(UTC),
        )
        self.created.append(asset)
        return asset


class FakeAssetStatusRepository:
    def __init__(self):
        self.changes = []

    def record_status_change(self, asset_id, status, reason=None):
        self.changes.append((asset_id, status, reason))


class FakeScreenedUniverseRepository:
    def __init__(self):
        self.inserted = []

    def insert_many(self, rows):
        self.inserted.extend(rows)


class FakeMarketRegimeRepository:
    def __init__(self):
        self.inserted = []

    def insert(self, snapshot):
        self.inserted.append(snapshot)


class FakeSignalSourceRepository:
    def __init__(self):
        self.statuses = {}

    def update_status(self, name, status, notes=None):
        self.statuses[name] = status


class FakeCoinGeckoClient:
    def __init__(self, entries):
        self._entries = entries

    def fetch_top_markets(self, limit):
        return self._entries[:limit]


class FakeCoinMarketCapClient:
    def __init__(self, configured=False, quotes=None):
        self._configured = configured
        self._quotes = quotes or {}

    @property
    def is_configured(self):
        return self._configured

    def fetch_quotes(self, symbols):
        return {s: self._quotes[s] for s in symbols if s in self._quotes}


class FakeVenueClient:
    """Shared fake for Binance/Coinbase — same shape, different method names
    used by ScreeningService (list_usdt_symbols/list_usd_products,
    fetch_daily_ohlcv)."""

    def __init__(self, listed_symbols, ohlcv_by_symbol=None):
        self._listed = listed_symbols
        self._ohlcv = ohlcv_by_symbol or {}

    def list_usdt_symbols(self):
        return self._listed

    def list_usd_products(self):
        return self._listed

    def fetch_daily_ohlcv(self, symbol, days):
        return self._ohlcv.get(symbol)


def _entry(symbol, coingecko_id=None, market_cap=1_000_000, volume=100_000, momentum_7d=0.05, momentum_30d=0.20, price=10.0):
    return {
        "symbol": symbol,
        "id": coingecko_id or symbol.lower(),
        "name": symbol,
        "market_cap": market_cap,
        "total_volume": volume,
        "current_price": price,
        "price_change_percentage_7d_in_currency": momentum_7d,
        "price_change_percentage_30d_in_currency": momentum_30d,
    }


def _make_service(
    entries, cmc=None, binance=None, coinbase=None,
    asset_repo=None, asset_status_repo=None, screened_repo=None, regime_repo=None, signal_repo=None,
    top_candidates_size=2,
):
    settings = Settings(_env_file=None, screening_universe_size=10, top_candidates_size=top_candidates_size)
    return settings, ScreeningService(
        settings=settings,
        asset_repo=asset_repo or FakeAssetRepository(),
        asset_status_repo=asset_status_repo or FakeAssetStatusRepository(),
        screened_universe_repo=screened_repo or FakeScreenedUniverseRepository(),
        regime_repo=regime_repo or FakeMarketRegimeRepository(),
        signal_source_repo=signal_repo or FakeSignalSourceRepository(),
        coingecko_client=FakeCoinGeckoClient(entries),
        coinmarketcap_client=cmc or FakeCoinMarketCapClient(configured=False),
        coinbase_client=coinbase or FakeVenueClient(set()),
        binance_client=binance or FakeVenueClient(set()),
    )


# --- Tests ---------------------------------------------------------------

def test_filters_stablecoins_from_universe():
    entries = [_entry("BTC"), _entry("USDT"), _entry("ETH")]
    _, service = _make_service(entries)
    result = service.run("RUN-1")
    assert result.screened_count == 2  # USDT excluded


def test_ranks_by_composite_score_and_tags_top_candidates():
    entries = [
        _entry("BTC", momentum_30d=0.10),
        _entry("GOOD", momentum_30d=0.80),
        _entry("BAD", momentum_30d=-0.30),
    ]
    _, service = _make_service(entries, top_candidates_size=2)
    result = service.run("RUN-1")
    assert set(result.top_candidates) == {"BTC", "GOOD"} or "GOOD" in result.top_candidates
    assert len(result.top_candidates) == 2


def test_promotes_genuinely_new_candidate_as_asset_with_candidate_status():
    entries = [_entry("BTC"), _entry("NEWCOIN", momentum_30d=0.90)]
    asset_repo = FakeAssetRepository()
    asset_status_repo = FakeAssetStatusRepository()
    _, service = _make_service(entries, asset_repo=asset_repo, asset_status_repo=asset_status_repo, top_candidates_size=2)

    result = service.run("RUN-1")

    assert "NEWCOIN" in result.new_candidates
    assert len(asset_repo.created) == 2  # both BTC and NEWCOIN are "new" here (no pre-existing assets)
    assert any(status == "CANDIDATE" for _id, status, _reason in asset_status_repo.changes)


def test_reuses_existing_asset_id_instead_of_creating_duplicate():
    entries = [_entry("BTC"), _entry("ETH")]
    existing_btc = Asset(
        id="existing-btc-id", symbol="BTC", name="Bitcoin", coingecko_id="btc",
        active=True, in_asset=True, created_at=datetime.now(UTC),
    )
    asset_repo = FakeAssetRepository(existing_by_coingecko_id={"btc": existing_btc})
    _, service = _make_service(entries, asset_repo=asset_repo, top_candidates_size=2)

    service.run("RUN-1")

    assert not any(a.symbol == "BTC" for a in asset_repo.created)


def test_volatility_uses_binance_when_listed():
    ohlcv = [(float(100 + i), 1000.0) for i in range(31)]
    entries = [_entry("BTC")]
    binance = FakeVenueClient({"BTC"}, {"BTC": ohlcv})
    screened_repo = FakeScreenedUniverseRepository()
    _, service = _make_service(entries, binance=binance, screened_repo=screened_repo, top_candidates_size=1)

    service.run("RUN-1")

    row = screened_repo.inserted[0]
    assert row.volatility_drawdown_source == "BINANCE"
    assert row.volatility_30d is not None


def test_volatility_falls_back_to_coinbase_when_not_on_binance():
    ohlcv = [(float(100 + i), 1000.0) for i in range(31)]
    entries = [_entry("HYPE")]
    coinbase = FakeVenueClient({"HYPE"}, {"HYPE": ohlcv})
    screened_repo = FakeScreenedUniverseRepository()
    _, service = _make_service(entries, binance=FakeVenueClient(set()), coinbase=coinbase, screened_repo=screened_repo, top_candidates_size=1)

    service.run("RUN-1")

    row = screened_repo.inserted[0]
    assert row.volatility_drawdown_source == "COINBASE"


def test_volatility_unavailable_when_neither_venue_lists_asset():
    entries = [_entry("OBSCURE")]
    screened_repo = FakeScreenedUniverseRepository()
    _, service = _make_service(entries, screened_repo=screened_repo, top_candidates_size=1)

    service.run("RUN-1")

    row = screened_repo.inserted[0]
    assert row.volatility_drawdown_source == "UNAVAILABLE"
    assert row.volatility_30d is None
    assert row.drawdown_30d is None


def test_anomaly_flag_recorded_when_price_spikes():
    closes = [100.0] * 30 + [300.0]  # 200% jump on the last day
    ohlcv = [(c, 1000.0) for c in closes]
    entries = [_entry("SPIKY")]
    binance = FakeVenueClient({"SPIKY"}, {"SPIKY": ohlcv})
    _, service = _make_service(entries, binance=binance, top_candidates_size=1)

    result = service.run("RUN-1")

    assert any(symbol == "SPIKY" for symbol, _reason in result.anomalies)


def test_regime_snapshot_notes_flag_missing_altcoin_season_without_cmc():
    entries = [_entry("BTC"), _entry("ETH")]
    regime_repo = FakeMarketRegimeRepository()
    _, service = _make_service(entries, regime_repo=regime_repo, top_candidates_size=2)

    service.run("RUN-1")

    snapshot = regime_repo.inserted[0]
    assert snapshot.inputs["altcoin_season_index_available"] is False
    assert snapshot.inputs["altcoin_season_index"] is None


def test_regime_snapshot_populates_halving_cycle_days_always():
    entries = [_entry("BTC")]
    regime_repo = FakeMarketRegimeRepository()
    _, service = _make_service(entries, regime_repo=regime_repo, top_candidates_size=1)

    service.run("RUN-1")

    inputs = regime_repo.inserted[0].inputs
    assert inputs["days_since_halving"] >= 0
    assert inputs["days_until_next_halving_estimated"] > 0


def test_signal_source_statuses_updated_after_run():
    entries = [_entry("BTC")]
    signal_repo = FakeSignalSourceRepository()
    _, service = _make_service(entries, signal_repo=signal_repo, top_candidates_size=1)

    service.run("RUN-1")

    assert signal_repo.statuses["CoinMarketCap"] == "NOT_IMPLEMENTED"
    assert signal_repo.statuses["Coinbase"] == "OK"
    assert signal_repo.statuses["Binance"] == "OK"


def test_empty_universe_returns_empty_result_without_crashing():
    _, service = _make_service([])
    result = service.run("RUN-1")
    assert result.screened_count == 0


def test_coingecko_failure_does_not_crash_the_run():
    class FailingCoinGeckoClient:
        def fetch_top_markets(self, limit):
            raise RuntimeError("network down")

    settings = Settings(_env_file=None, screening_universe_size=10, top_candidates_size=2)
    service = ScreeningService(
        settings=settings,
        asset_repo=FakeAssetRepository(),
        asset_status_repo=FakeAssetStatusRepository(),
        screened_universe_repo=FakeScreenedUniverseRepository(),
        regime_repo=FakeMarketRegimeRepository(),
        signal_source_repo=FakeSignalSourceRepository(),
        coingecko_client=FailingCoinGeckoClient(),
        coinmarketcap_client=FakeCoinMarketCapClient(configured=False),
        coinbase_client=FakeVenueClient(set()),
        binance_client=FakeVenueClient(set()),
    )

    result = service.run("RUN-1")

    assert result.screened_count == 0


def test_cross_source_price_disagreement_is_logged(caplog):
    # CoinGecko says $100, Binance's OHLCV close says $150 -> 50% spread, well
    # past the logging threshold.
    ohlcv = [(100.0, 1000.0)] * 30 + [(150.0, 1000.0)]
    entries = [_entry("BTC", price=100.0)]
    binance = FakeVenueClient({"BTC"}, {"BTC": ohlcv})
    _, service = _make_service(entries, binance=binance, top_candidates_size=1)

    with caplog.at_level("INFO", logger="crypto_ai_portfolio.market_data"):
        service.run("RUN-1")

    assert any("disagreement" in record.message for record in caplog.records)
