from datetime import UTC, datetime

from app.database.models import Asset
from app.market_data.derivatives_service import DerivativesService

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


class FakeScreenedUniverseRepo:
    def __init__(self, volatility_by_symbol=None):
        self._vol = volatility_by_symbol or {}

    def get_latest_volatility(self, symbol):
        return self._vol.get(symbol)


class FakeSignalSourceRepo:
    def __init__(self):
        self.statuses = {}
        self.notes = {}

    def update_status(self, name, status, notes=None):
        self.statuses[name] = status
        if notes is not None:
            self.notes[name] = notes


class FakeBinanceClient:
    def __init__(self, perp_symbols=None, funding=None, oi=None, tickers=None, dated_futures=None, futures_prices=None, raise_on_perp_list=False):
        self._perp_symbols = perp_symbols or set()
        self._funding = funding or {}
        self._oi = oi or {}
        self._tickers = tickers or {}
        self._dated_futures = dated_futures or {}
        self._futures_prices = futures_prices or {}
        self._raise_on_perp_list = raise_on_perp_list

    def list_perpetual_symbols(self):
        if self._raise_on_perp_list:
            raise RuntimeError("network down")
        return self._perp_symbols

    def fetch_funding_rate(self, symbol):
        return self._funding.get(symbol)

    def fetch_open_interest(self, symbol):
        return self._oi.get(symbol)

    def fetch_ticker_24hr(self, symbol):
        return self._tickers.get(symbol)

    def list_dated_futures(self, symbol):
        return self._dated_futures.get(symbol, [])

    def fetch_futures_price(self, futures_symbol):
        return self._futures_prices.get(futures_symbol)


class FakeDeribitClient:
    def __init__(self, oi_by_currency=None, atm_option=None, put_call_ratio=None, tickers=None, dated_futures=None):
        self._oi = oi_by_currency or {}
        self._atm_option = atm_option or {}
        self._put_call = put_call_ratio or {}
        self._tickers = tickers or {}
        self._dated_futures = dated_futures or {}

    def fetch_futures_open_interest(self, currency):
        return self._oi.get(currency, {})

    def find_near_atm_option(self, currency, spot_price):
        return self._atm_option.get(currency)

    def fetch_options_put_call_oi_ratio(self, currency):
        return self._put_call.get(currency)

    def fetch_ticker(self, instrument_name):
        return self._tickers.get(instrument_name)

    def list_dated_futures(self, currency):
        return self._dated_futures.get(currency, [])


class FakeCftcClient:
    def __init__(self, reports=None):
        self._reports = reports or {}

    def fetch_latest_report(self, symbol):
        return self._reports.get(symbol)


class FakeDefiLlamaClient:
    def __init__(self, protocols=None, protocol_by_symbol=None, stablecoins=None):
        self._protocols = protocols or []
        self._protocol_by_symbol = protocol_by_symbol or {}
        self._stablecoins = stablecoins or []

    def fetch_protocols(self):
        return self._protocols

    def find_protocol_by_symbol(self, symbol, protocols=None):
        return self._protocol_by_symbol.get(symbol)

    def fetch_stablecoins(self):
        return self._stablecoins


class FakeEtherscanClient:
    def __init__(self, configured=False, count=None):
        self._configured = configured
        self._count = count

    @property
    def is_configured(self):
        return self._configured

    def count_large_transfers_last_24h(self):
        return self._count


class FakeGlassnodeClient:
    def __init__(self, configured=False):
        self._configured = configured

    @property
    def is_configured(self):
        return self._configured


def _make_service(
    assets, binance=None, deribit=None, cftc=None, defillama=None, etherscan=None, glassnode=None,
    evidence_repo=None, screened_repo=None, signal_repo=None,
):
    return DerivativesService(
        asset_repo=FakeAssetRepo(assets),
        evidence_repo=evidence_repo or FakeEvidenceRepo(),
        screened_universe_repo=screened_repo or FakeScreenedUniverseRepo(),
        signal_source_repo=signal_repo or FakeSignalSourceRepo(),
        binance_client=binance or FakeBinanceClient(),
        deribit_client=deribit or FakeDeribitClient(),
        cftc_client=cftc or FakeCftcClient(),
        defillama_client=defillama or FakeDefiLlamaClient(),
        etherscan_client=etherscan or FakeEtherscanClient(),
        glassnode_client=glassnode or FakeGlassnodeClient(),
    )


# --- Tests -----------------------------------------------------------------

def test_collects_funding_and_oi_for_assets_with_perpetuals():
    assets = [_asset("BTC"), _asset("LINK")]
    binance = FakeBinanceClient(
        perp_symbols={"BTC", "LINK"},
        funding={"BTC": {"lastFundingRate": "0.0001", "nextFundingTime": 123, "markPrice": "80000"}},
        oi={"BTC": 12345.0},
    )
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(assets, binance=binance, evidence_repo=evidence_repo)

    result = service.run("RUN-1")

    assert set(result.funding_rate_assets) == {"BTC", "LINK"}
    sources = {o.source for o in evidence_repo.inserted}
    assert "binance_funding_rate" in sources
    assert "binance_open_interest" in sources


def test_only_btc_eth_get_deep_derivatives():
    assets = [_asset("BTC"), _asset("SOL")]
    service = _make_service(assets)

    result = service.run("RUN-1")

    assert result.deep_derivatives_assets == ["BTC"]


def test_vrp_computed_when_iv_and_realized_vol_available():
    assets = [_asset("BTC")]
    binance = FakeBinanceClient(tickers={"BTC": {"lastPrice": "80000"}})
    deribit = FakeDeribitClient(
        atm_option={"BTC": {"instrument_name": "BTC-1JAN27-80000-C"}},
        tickers={"BTC-1JAN27-80000-C": {"mark_iv": 60.0}},
    )
    screened_repo = FakeScreenedUniverseRepo(volatility_by_symbol={"BTC": 0.02})
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(assets, binance=binance, deribit=deribit, screened_repo=screened_repo, evidence_repo=evidence_repo)

    service.run("RUN-1")

    vrp_obs = [o for o in evidence_repo.inserted if o.source == "volatility_risk_premium"]
    assert len(vrp_obs) == 1
    assert vrp_obs[0].payload["vrp"] is not None
    assert vrp_obs[0].payload["implied_vol_annualized"] == 60.0


def test_vrp_not_computed_when_realized_vol_missing():
    assets = [_asset("BTC")]
    binance = FakeBinanceClient(tickers={"BTC": {"lastPrice": "80000"}})
    deribit = FakeDeribitClient(
        atm_option={"BTC": {"instrument_name": "BTC-1JAN27-80000-C"}},
        tickers={"BTC-1JAN27-80000-C": {"mark_iv": 60.0}},
    )
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(assets, binance=binance, deribit=deribit, evidence_repo=evidence_repo, screened_repo=FakeScreenedUniverseRepo())

    service.run("RUN-1")

    vrp_obs = [o for o in evidence_repo.inserted if o.source == "volatility_risk_premium"]
    assert vrp_obs == []


def test_cftc_cot_captured_for_btc_and_eth():
    assets = [_asset("BTC"), _asset("ETH")]
    cftc = FakeCftcClient(reports={
        "BTC": {"report_date_as_yyyy_mm_dd": "2026-09-01T00:00:00.000", "open_interest_all": "19697",
                "dealer_positions_long_all": "6626", "dealer_positions_short_all": "3842",
                "asset_mgr_positions_long": "1", "asset_mgr_positions_short": "1",
                "lev_money_positions_long": "1", "lev_money_positions_short": "1",
                "other_rept_positions_long": "1", "other_rept_positions_short": "1"},
        "ETH": {"report_date_as_yyyy_mm_dd": "2026-09-01T00:00:00.000", "open_interest_all": "100",
                "dealer_positions_long_all": "1", "dealer_positions_short_all": "1",
                "asset_mgr_positions_long": "1", "asset_mgr_positions_short": "1",
                "lev_money_positions_long": "1", "lev_money_positions_short": "1",
                "other_rept_positions_long": "1", "other_rept_positions_short": "1"},
    })
    evidence_repo = FakeEvidenceRepo()
    signal_repo = FakeSignalSourceRepo()
    service = _make_service(assets, cftc=cftc, evidence_repo=evidence_repo, signal_repo=signal_repo)

    service.run("RUN-1")

    cot_obs = [o for o in evidence_repo.inserted if o.source == "cftc_cot"]
    assert len(cot_obs) == 2
    assert cot_obs[0].freshness == "STALE"  # by design, weekly report
    assert signal_repo.statuses["CME_COT_POSITIONING"] == "OK"


def test_cftc_cot_unavailable_when_no_report_found():
    assets = [_asset("BTC")]
    cftc = FakeCftcClient(reports={})  # no data for BTC
    signal_repo = FakeSignalSourceRepo()
    service = _make_service(assets, cftc=cftc, signal_repo=signal_repo)

    service.run("RUN-1")

    assert signal_repo.statuses["CME_COT_POSITIONING"] == "UNAVAILABLE"


def test_defillama_tvl_matched_by_symbol():
    assets = [_asset("UNI")]
    defillama = FakeDefiLlamaClient(protocol_by_symbol={"UNI": {"name": "Uniswap V3", "tvl": 1_500_000_000, "change_7d": 3.8}})
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(assets, defillama=defillama, evidence_repo=evidence_repo)

    result = service.run("RUN-1")

    assert result.tvl_matches == ["UNI"]
    tvl_obs = [o for o in evidence_repo.inserted if o.source == "defillama_tvl"]
    assert tvl_obs[0].payload["protocol"] == "Uniswap V3"


def test_stablecoin_supply_captured_as_global_scope():
    assets = [_asset("BTC")]
    stablecoins = [{
        "name": "Tether", "symbol": "USDT",
        "circulating": {"peggedUSD": 183_000_000_000},
        "circulatingPrevWeek": {"peggedUSD": 180_000_000_000},
        "circulatingPrevMonth": {"peggedUSD": 175_000_000_000},
    }]
    defillama = FakeDefiLlamaClient(stablecoins=stablecoins)
    evidence_repo = FakeEvidenceRepo()
    service = _make_service(assets, defillama=defillama, evidence_repo=evidence_repo)

    result = service.run("RUN-1")

    assert result.stablecoins_captured == 1
    sc_obs = [o for o in evidence_repo.inserted if o.source == "defillama_stablecoin_supply"][0]
    assert sc_obs.scope == "GLOBAL_CRYPTO"
    assert sc_obs.asset_id is None
    assert sc_obs.payload["growth_7d"] is not None
    assert sc_obs.payload["growth_30d"] is not None


def test_etherscan_not_implemented_when_unconfigured():
    assets = [_asset("ETH")]
    signal_repo = FakeSignalSourceRepo()
    service = _make_service(assets, etherscan=FakeEtherscanClient(configured=False), signal_repo=signal_repo)

    result = service.run("RUN-1")

    assert result.etherscan_captured is False
    assert signal_repo.statuses["Etherscan"] == "NOT_IMPLEMENTED"


def test_etherscan_captured_when_configured():
    assets = [_asset("ETH")]
    evidence_repo = FakeEvidenceRepo()
    signal_repo = FakeSignalSourceRepo()
    service = _make_service(
        assets, etherscan=FakeEtherscanClient(configured=True, count=7),
        evidence_repo=evidence_repo, signal_repo=signal_repo,
    )

    result = service.run("RUN-1")

    assert result.etherscan_captured is True
    assert signal_repo.statuses["Etherscan"] == "OK"
    obs = [o for o in evidence_repo.inserted if o.source == "etherscan_large_transfer_count"][0]
    assert obs.payload["large_transfer_count_24h"] == 7
    assert "limitation" in obs.payload


def test_glassnode_not_implemented_when_unconfigured():
    assets = [_asset("BTC")]
    signal_repo = FakeSignalSourceRepo()
    service = _make_service(assets, glassnode=FakeGlassnodeClient(configured=False), signal_repo=signal_repo)

    service.run("RUN-1")

    assert signal_repo.statuses["ON_CHAIN_VALUATION_METRICS"] == "NOT_IMPLEMENTED"
    assert signal_repo.statuses["ON_CHAIN_MINER_METRICS"] == "NOT_IMPLEMENTED"


def test_one_source_failure_does_not_crash_the_run():
    assets = [_asset("BTC")]
    binance = FakeBinanceClient(raise_on_perp_list=True)
    signal_repo = FakeSignalSourceRepo()
    service = _make_service(assets, binance=binance, signal_repo=signal_repo)

    result = service.run("RUN-1")

    assert signal_repo.statuses["Binance"] == "UNAVAILABLE"
    # Deep derivatives (BTC) should still have been attempted despite the
    # perpetual-listing failure.
    assert result.deep_derivatives_assets == ["BTC"]


def test_empty_asset_list_does_not_crash():
    service = _make_service([])
    result = service.run("RUN-1")
    assert result.funding_rate_assets == []
    assert result.deep_derivatives_assets == []


def test_all_five_dead_end_sources_reaffirmed_not_just_glassnode_gated_ones():
    # ON_CHAIN_VALUATION_METRICS/ON_CHAIN_MINER_METRICS come from the
    # Glassnode gate; SPOT_ETF_FLOWS/TOKEN_UNLOCK_SCHEDULE/PREDICTION_MARKETS
    # were investigated in 3c with no code path at all (no client to gate on)
    # — this proves they're still actively reaffirmed every run, with an
    # explanatory note, not just silently left at whatever 3a originally
    # seeded.
    assets = [_asset("BTC")]
    signal_repo = FakeSignalSourceRepo()
    service = _make_service(assets, signal_repo=signal_repo)

    service.run("RUN-1")

    for name in ("ON_CHAIN_VALUATION_METRICS", "ON_CHAIN_MINER_METRICS",
                 "SPOT_ETF_FLOWS", "TOKEN_UNLOCK_SCHEDULE", "PREDICTION_MARKETS"):
        assert signal_repo.statuses[name] == "NOT_IMPLEMENTED", name

    for name in ("SPOT_ETF_FLOWS", "TOKEN_UNLOCK_SCHEDULE", "PREDICTION_MARKETS"):
        assert name in signal_repo.notes, name
        assert len(signal_repo.notes[name]) > 20
