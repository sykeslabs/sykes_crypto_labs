from datetime import UTC, datetime

from app.config.settings import Settings
from app.database.models import Asset
from app.market_data.screening_service import ScreeningService
from app.portfolio.schemas import HoldingsLedgerEntry

# --- Fakes -------------------------------------------------------------------


class FakeAssetRepository:
    def __init__(self, existing_by_coingecko_id=None, existing_by_id=None):
        self._existing = existing_by_coingecko_id or {}
        self._existing_by_id = existing_by_id or {}
        self.created = []

    def get_by_coingecko_id(self, coingecko_id):
        return self._existing.get(coingecko_id)

    def get_by_id(self, asset_id):
        return self._existing_by_id.get(asset_id)

    def create_asset(self, symbol, name, coingecko_id, coinmarketcap_id=None, active=True, in_asset=False):
        asset = Asset(
            id=f"new-{symbol}", symbol=symbol, name=name, coingecko_id=coingecko_id,
            coinmarketcap_id=coinmarketcap_id, active=active, in_asset=in_asset,
            created_at=datetime.now(UTC),
        )
        self.created.append(asset)
        return asset


class FakeHoldingsLedgerRepository:
    def __init__(self, history=None):
        self._history = history or []

    def get_all_history(self):
        return self._history


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
    def __init__(self, entries, extra_by_id=None):
        self._entries = entries
        # Simulates a direct `/coins/markets?ids=...` lookup for a specific
        # held asset that fell outside `fetch_top_markets`' own top-N --
        # keyed by coingecko_id, same shape `fetch_markets` really returns.
        self._extra_by_id = extra_by_id or {}
        self.fetch_markets_calls: list[list[str]] = []

    def fetch_top_markets(self, limit):
        return self._entries[:limit]

    def fetch_markets(self, coingecko_ids):
        self.fetch_markets_calls.append(list(coingecko_ids))
        return {cid: self._extra_by_id[cid] for cid in coingecko_ids if cid in self._extra_by_id}


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
    holdings_ledger_repo=None, top_candidates_size=2, coingecko=None, coingecko_extra_by_id=None,
):
    settings = Settings(_env_file=None, screening_universe_size=10, top_candidates_size=top_candidates_size)
    return settings, ScreeningService(
        settings=settings,
        asset_repo=asset_repo or FakeAssetRepository(),
        asset_status_repo=asset_status_repo or FakeAssetStatusRepository(),
        screened_universe_repo=screened_repo or FakeScreenedUniverseRepository(),
        regime_repo=regime_repo or FakeMarketRegimeRepository(),
        signal_source_repo=signal_repo or FakeSignalSourceRepository(),
        coingecko_client=coingecko or FakeCoinGeckoClient(entries, extra_by_id=coingecko_extra_by_id),
        coinmarketcap_client=cmc or FakeCoinMarketCapClient(configured=False),
        coinbase_client=coinbase or FakeVenueClient(set()),
        binance_client=binance or FakeVenueClient(set()),
        holdings_ledger_repo=holdings_ledger_repo or FakeHoldingsLedgerRepository(),
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


def test_currently_held_asset_outside_top_n_still_gets_judge_coverage():
    # BTC ranks 3rd of 3 by composite score -- would normally miss a
    # top_candidates_size=2 cutoff entirely, the exact real-world gap
    # (BTC held but un-judged for a week) that prompted this fix.
    entries = [
        _entry("BTC", momentum_30d=0.10),
        _entry("GOOD", momentum_30d=0.80),
        _entry("BEST", momentum_30d=0.90),
    ]
    asset_repo = FakeAssetRepository(existing_by_id={
        "btc-asset-id": Asset(
            id="btc-asset-id", symbol="BTC", name="Bitcoin", coingecko_id="btc",
            active=True, in_asset=True, created_at=datetime.now(UTC),
        ),
    })
    holdings_ledger_repo = FakeHoldingsLedgerRepository([
        HoldingsLedgerEntry(asset_id="btc-asset-id", quantity=1.0, recorded_at=datetime.now(UTC)),
    ])
    _, service = _make_service(
        entries, asset_repo=asset_repo, holdings_ledger_repo=holdings_ledger_repo, top_candidates_size=2,
    )

    result = service.run("RUN-1")

    assert set(result.top_candidates) == {"BTC", "GOOD", "BEST"}


def test_held_asset_missing_from_universe_entirely_logs_warning(caplog):
    # A held asset that isn't in today's top-N screened universe AND can't
    # be found via the direct CoinGecko lookup either (e.g. delisted, or a
    # genuinely bad coingecko_id) -- this must be a disclosed warning, never
    # a silent drop. No `ghost` entry is registered in coingecko_extra_by_id
    # below, so the direct lookup genuinely finds nothing, same as a real
    # CoinGecko 404/empty response.
    entries = [_entry("GOOD", momentum_30d=0.80)]
    asset_repo = FakeAssetRepository(existing_by_id={
        "ghost-id": Asset(
            id="ghost-id", symbol="GHOST", name="Ghost", coingecko_id="ghost",
            active=True, in_asset=True, created_at=datetime.now(UTC),
        ),
    })
    holdings_ledger_repo = FakeHoldingsLedgerRepository([
        HoldingsLedgerEntry(asset_id="ghost-id", quantity=1.0, recorded_at=datetime.now(UTC)),
    ])
    _, service = _make_service(
        entries, asset_repo=asset_repo, holdings_ledger_repo=holdings_ledger_repo, top_candidates_size=1,
    )

    with caplog.at_level("WARNING"):
        result = service.run("RUN-1")

    assert "GHOST" not in result.top_candidates
    assert any("GHOST" in record.message for record in caplog.records)


def test_held_asset_outside_top_n_universe_is_rescued_via_direct_lookup():
    # Real fix for the JASMY finding (2026-09-16, see doc/history.md's
    # Phase 5f section): a held asset that fell out of _build_universe's
    # own top-N-by-market-cap fetch is now fetched directly by coingecko_id
    # instead of only being logged as permanently missing.
    entries = [_entry("GOOD", momentum_30d=0.80)]
    asset_repo = FakeAssetRepository(existing_by_id={
        "jasmy-id": Asset(
            id="jasmy-id", symbol="JASMY", name="JasmyCoin", coingecko_id="jasmycoin",
            active=True, in_asset=True, created_at=datetime.now(UTC),
        ),
    })
    holdings_ledger_repo = FakeHoldingsLedgerRepository([
        HoldingsLedgerEntry(asset_id="jasmy-id", quantity=1.0, recorded_at=datetime.now(UTC)),
    ])
    _, service = _make_service(
        entries, asset_repo=asset_repo, holdings_ledger_repo=holdings_ledger_repo, top_candidates_size=1,
        coingecko_extra_by_id={"jasmycoin": _entry("JASMY", coingecko_id="jasmycoin", momentum_30d=-0.50)},
    )

    result = service.run("RUN-1")

    assert "JASMY" in result.top_candidates  # rescued by the held-symbol override, same as before
    assert result.screened_count == 2  # GOOD (top-N) + the directly-fetched JASMY


def test_held_asset_lookup_failure_is_handled_gracefully_and_logged(caplog):
    # The direct lookup itself can fail (network error, bad API response) --
    # this must degrade to the existing "no coverage this run" warning, not
    # crash the whole screening run.
    entries = [_entry("GOOD", momentum_30d=0.80)]

    class BrokenCoinGeckoClient(FakeCoinGeckoClient):
        def fetch_markets(self, coingecko_ids):
            raise RuntimeError("simulated CoinGecko outage")

    asset_repo = FakeAssetRepository(existing_by_id={
        "jasmy-id": Asset(
            id="jasmy-id", symbol="JASMY", name="JasmyCoin", coingecko_id="jasmycoin",
            active=True, in_asset=True, created_at=datetime.now(UTC),
        ),
    })
    holdings_ledger_repo = FakeHoldingsLedgerRepository([
        HoldingsLedgerEntry(asset_id="jasmy-id", quantity=1.0, recorded_at=datetime.now(UTC)),
    ])
    _, service = _make_service(
        entries, asset_repo=asset_repo, holdings_ledger_repo=holdings_ledger_repo, top_candidates_size=1,
        coingecko=BrokenCoinGeckoClient(entries),
    )

    with caplog.at_level("WARNING"):
        result = service.run("RUN-1")

    assert "JASMY" not in result.top_candidates
    assert result.screened_count == 1  # only GOOD -- the run itself did not crash
    assert any("JASMY" in record.message for record in caplog.records)


def test_held_asset_already_in_top_n_universe_is_not_fetched_again_or_duplicated():
    # Preserves "no duplicate rows": a held asset already present in
    # _build_universe's own top-N fetch must not trigger a second, direct
    # lookup, and must not appear twice in the persisted screened universe.
    entries = [_entry("BTC", coingecko_id="bitcoin", momentum_30d=0.10), _entry("GOOD", momentum_30d=0.80)]
    asset_repo = FakeAssetRepository(existing_by_id={
        "btc-id": Asset(
            id="btc-id", symbol="BTC", name="Bitcoin", coingecko_id="bitcoin",
            active=True, in_asset=True, created_at=datetime.now(UTC),
        ),
    })
    holdings_ledger_repo = FakeHoldingsLedgerRepository([
        HoldingsLedgerEntry(asset_id="btc-id", quantity=1.0, recorded_at=datetime.now(UTC)),
    ])
    coingecko = FakeCoinGeckoClient(entries, extra_by_id={"bitcoin": _entry("BTC", coingecko_id="bitcoin")})
    screened_repo = FakeScreenedUniverseRepository()
    _, service = _make_service(
        entries, asset_repo=asset_repo, holdings_ledger_repo=holdings_ledger_repo, top_candidates_size=2,
        coingecko=coingecko, screened_repo=screened_repo,
    )

    result = service.run("RUN-1")

    assert coingecko.fetch_markets_calls == []  # BTC was already present -- no direct lookup needed
    assert result.screened_count == 2  # BTC + GOOD, no duplicate
    assert [row.symbol for row in screened_repo.inserted].count("BTC") == 1


def test_promotes_genuinely_new_candidate_as_asset_with_candidate_status():
    entries = [_entry("BTC"), _entry("NEWCOIN", momentum_30d=0.90)]
    asset_repo = FakeAssetRepository()
    asset_status_repo = FakeAssetStatusRepository()
    _, service = _make_service(entries, asset_repo=asset_repo, asset_status_repo=asset_status_repo, top_candidates_size=2)

    result = service.run("RUN-1")

    assert "NEWCOIN" in result.new_candidates
    assert len(asset_repo.created) == 2  # both BTC and NEWCOIN are "new" here (no pre-existing assets)
    assert any(status == "CANDIDATE" for _id, status, _reason in asset_status_repo.changes)


def test_promoted_new_candidate_gets_coingeckos_real_display_name_not_the_bare_symbol():
    # Real bug fixed 2026-09-16, found live: CoinGecko's real display name
    # (e.g. "Zcash") was already fetched into _build_universe's own dict but
    # never threaded through ScreenedAsset, so every newly-promoted asset's
    # `name` silently fell back to the bare symbol ("ZEC") instead -- 14 of
    # 29 real tracked assets had this exact symptom live. _entry's default
    # (name == symbol) wouldn't catch this, so this test overrides `name`
    # explicitly to something that genuinely differs from the symbol.
    entry = _entry("ZEC", momentum_30d=0.90)
    entry["name"] = "Zcash"
    entries = [_entry("BTC"), entry]
    asset_repo = FakeAssetRepository()
    _, service = _make_service(entries, asset_repo=asset_repo, top_candidates_size=2)

    service.run("RUN-1")

    created_by_symbol = {a.symbol: a for a in asset_repo.created}
    assert created_by_symbol["ZEC"].name == "Zcash"


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
        holdings_ledger_repo=FakeHoldingsLedgerRepository(),
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
