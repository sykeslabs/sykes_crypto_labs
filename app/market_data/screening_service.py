import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import Settings
from app.database.models import Asset
from app.database.repository import (
    AssetRepository,
    AssetStatusRepository,
    HoldingsLedgerRepository,
    MarketRegimeRepository,
    MarketSnapshotRepository,
    ScreenedUniverseRepository,
    SignalSourceRepository,
)
from app.market_data.anomaly import detect_anomaly
from app.market_data.binance import BinanceClient
from app.market_data.coinbase import CoinbaseClient
from app.market_data.coingecko import CoinGeckoClient
from app.market_data.coinmarketcap import CoinMarketCapClient
from app.market_data.factors import compute_composite_factor_scores, compute_max_drawdown, compute_relative_strength, compute_volatility
from app.market_data.regime import (
    classify_risk_regime,
    compute_altcoin_season_index,
    compute_breadth_pct,
    compute_btc_dominance,
    compute_halving_cycle_days,
    moving_average,
)
from app.market_data.screening_schemas import MarketRegimeSnapshot, ScreenedAsset
from app.market_data.stablecoins import is_stablecoin
from app.portfolio.holdings import aggregate_current_holdings, collapse_platforms, filter_materially_held

logger = logging.getLogger("crypto_ai_portfolio.market_data")

OHLCV_LOOKBACK_DAYS = 31


def _normalize_market_entry(entry: dict) -> dict:
    """Shared shape for a CoinGecko `/coins/markets` row, whether it came
    from `fetch_top_markets` (the bulk top-N-by-market-cap universe) or a
    direct `fetch_markets` lookup for a specific held asset that fell
    outside that universe -- so both paths feed the exact same downstream
    factor/ranking pipeline."""
    return {
        "symbol": entry["symbol"].upper(),
        "id": entry["id"],
        "name": entry["name"],
        "market_cap": entry.get("market_cap"),
        "total_volume": entry.get("total_volume"),
        "current_price": entry.get("current_price"),
        "momentum_7d": entry.get("price_change_percentage_7d_in_currency"),
        "momentum_30d": entry.get("price_change_percentage_30d_in_currency"),
    }


@dataclass
class ScreeningResult:
    screened_count: int = 0
    top_candidates: list[str] = field(default_factory=list)
    new_candidates: list[str] = field(default_factory=list)
    anomalies: list[tuple[str, str]] = field(default_factory=list)
    regime: str | None = None
    source_status: dict[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return (
            f"screened={self.screened_count} "
            f"top_candidates={self.top_candidates} "
            f"new_candidates={self.new_candidates} "
            f"regime={self.regime} "
            f"anomalies={len(self.anomalies)}"
        )


class ScreeningService:
    """3b: builds an open screening universe beyond the tracked assets,
    computes deterministic factors from CoinGecko/CoinMarketCap/Coinbase/
    Binance, ranks candidates, classifies one run-level market regime, and
    persists both. Zero LLM calls."""

    def __init__(
        self,
        settings: Settings,
        asset_repo: AssetRepository,
        asset_status_repo: AssetStatusRepository,
        screened_universe_repo: ScreenedUniverseRepository,
        regime_repo: MarketRegimeRepository,
        signal_source_repo: SignalSourceRepository,
        coingecko_client: CoinGeckoClient,
        coinmarketcap_client: CoinMarketCapClient,
        coinbase_client: CoinbaseClient,
        binance_client: BinanceClient,
        holdings_ledger_repo: HoldingsLedgerRepository,
        snapshot_repo: MarketSnapshotRepository,
    ) -> None:
        self._settings = settings
        self._asset_repo = asset_repo
        self._asset_status_repo = asset_status_repo
        self._screened_universe_repo = screened_universe_repo
        self._regime_repo = regime_repo
        self._signal_source_repo = signal_source_repo
        self._snapshot_repo = snapshot_repo
        self._coingecko = coingecko_client
        self._coinmarketcap = coinmarketcap_client
        self._coinbase = coinbase_client
        self._binance = binance_client
        self._holdings_ledger_repo = holdings_ledger_repo

    def run(self, run_id: str) -> ScreeningResult:
        result = ScreeningResult()
        now = datetime.now(UTC)

        try:
            universe = self._build_universe()
        except Exception as exc:
            logger.error("Failed to build screening universe from CoinGecko: %s", exc)
            return result

        held_assets = self._get_held_assets()
        universe = self._merge_missing_held_assets(universe, held_assets)

        result.screened_count = len(universe)
        if not universe:
            logger.warning("Screening universe is empty — nothing to do.")
            return result

        cmc_quotes, cmc_status = self._fetch_cmc_quotes([u["symbol"] for u in universe])
        binance_symbols, binance_status = self._safe_symbol_set(self._binance.list_usdt_symbols, "Binance")
        coinbase_symbols, coinbase_status = self._safe_symbol_set(self._coinbase.list_usd_products, "Coinbase")

        btc_entry = next((u for u in universe if u["symbol"] == "BTC"), None)
        btc_momentum_30d = btc_entry["momentum_30d"] if btc_entry else None
        btc_closes: list[float] = []

        screened_rows: list[ScreenedAsset] = []
        factor_inputs: list[dict[str, float | None]] = []
        momentum_90d_by_symbol: dict[str, float | None] = {}

        for entry in universe:
            symbol = entry["symbol"]
            closes, volumes, ohlcv_source = self._fetch_ohlcv(symbol, binance_symbols, coinbase_symbols)
            if symbol == "BTC":
                btc_closes = closes

            volatility = compute_volatility(closes) if closes else None
            drawdown = compute_max_drawdown(closes) if closes else None
            anomaly_flag, anomaly_reason = (
                detect_anomaly(closes, volumes) if closes and volumes else (False, None)
            )
            relative_strength = compute_relative_strength(entry["momentum_30d"], btc_momentum_30d)

            cmc_entry = cmc_quotes.get(symbol)
            cmc_quote = (cmc_entry or {}).get("quote", {}).get("USD", {})
            momentum_90d_by_symbol[symbol] = cmc_quote.get("percent_change_90d")

            source_prices = {"coingecko": entry.get("current_price")}
            if cmc_quote.get("price") is not None:
                source_prices["coinmarketcap"] = cmc_quote["price"]
            if closes:
                source_prices[ohlcv_source.lower()] = closes[-1]
            self._log_price_disagreement(symbol, source_prices)

            factors = {
                "momentum_30d": entry["momentum_30d"],
                "momentum_7d": entry["momentum_7d"],
                "relative_strength_30d": relative_strength,
                "volatility_30d": volatility,
                "drawdown_30d": drawdown,
                "volume_24h": entry.get("total_volume"),
            }
            factor_inputs.append(factors)

            if anomaly_flag:
                result.anomalies.append((symbol, anomaly_reason))

            screened_rows.append(
                ScreenedAsset(
                    run_id=run_id,
                    computed_at=now,
                    symbol=symbol,
                    name=entry.get("name"),
                    coingecko_id=entry["id"],
                    coinmarketcap_id=str(cmc_entry["id"]) if cmc_entry else None,
                    market_cap=entry.get("market_cap"),
                    volume_24h=entry.get("total_volume"),
                    momentum_7d=entry["momentum_7d"],
                    momentum_30d=entry["momentum_30d"],
                    volatility_30d=volatility,
                    drawdown_30d=drawdown,
                    volatility_drawdown_source=ohlcv_source,
                    relative_strength_30d=relative_strength,
                    anomaly_flag=anomaly_flag,
                    anomaly_reason=anomaly_reason,
                    source_prices=source_prices,
                )
            )

        composite_scores = compute_composite_factor_scores(factor_inputs)
        for row, score in zip(screened_rows, composite_scores, strict=True):
            row.composite_factor_score = score

        held_symbols = {a.symbol for a in held_assets}
        self._rank_and_tag_candidates(screened_rows, held_symbols)
        result.top_candidates = [r.symbol for r in screened_rows if r.is_top_candidate]

        result.new_candidates = self._promote_new_candidates(screened_rows, run_id)

        self._screened_universe_repo.insert_many(screened_rows)

        regime_snapshot = self._classify_regime(
            run_id, now, universe, factor_inputs, btc_entry, btc_closes,
            momentum_90d_by_symbol, btc_momentum_30d,
        )
        self._regime_repo.insert(regime_snapshot)
        result.regime = regime_snapshot.regime

        result.source_status = {
            "CoinMarketCap": cmc_status,
            "Coinbase": coinbase_status,
            "Binance": binance_status,
        }
        for name, status in result.source_status.items():
            self._signal_source_repo.update_status(name, status)

        logger.info("Screening complete: %s", result.summary)
        return result

    def _build_universe(self) -> list[dict]:
        raw = self._coingecko.fetch_top_markets(self._settings.screening_universe_size + 15)
        universe = []
        for entry in raw:
            normalized = _normalize_market_entry(entry)
            if is_stablecoin(normalized["symbol"]):
                continue
            universe.append(normalized)
            if len(universe) >= self._settings.screening_universe_size:
                break
        return universe

    def _merge_missing_held_assets(self, universe: list[dict], held_assets: list[Asset]) -> list[dict]:
        """A held asset can rank outside `_build_universe`'s own top-
        (screening_universe_size + 15)-by-market-cap fetch entirely, in
        which case the held-symbol override in `_rank_and_tag_candidates`
        never gets a row to act on (see that method's own WARNING) --
        confirmed live for JASMY, 2026-09-16. Fetches ONLY the held symbols
        actually missing from `universe` (never widens the global
        market-cap universe itself) via a single batched CoinGecko lookup
        by coingecko_id, normalized into the exact same shape
        `_build_universe` already produces, so they flow through the
        identical per-entry factor/ranking pipeline below."""
        present_symbols = {u["symbol"] for u in universe}
        missing = [a for a in held_assets if a.symbol not in present_symbols]
        if not missing:
            return universe

        try:
            markets = self._coingecko.fetch_markets([a.coingecko_id for a in missing])
        except Exception as exc:
            logger.warning(
                "Failed to fetch missing held asset(s) %s directly for screening coverage: %s",
                [a.symbol for a in missing], exc,
            )
            return universe

        for asset in missing:
            entry = markets.get(asset.coingecko_id)
            if entry is None:
                logger.warning(
                    "Held asset %s (coingecko_id=%s) could not be fetched directly either -- "
                    "still gets no Judge coverage this run.", asset.symbol, asset.coingecko_id,
                )
                continue
            normalized = _normalize_market_entry(entry)
            if is_stablecoin(normalized["symbol"]) or normalized["symbol"] in present_symbols:
                continue
            universe.append(normalized)
            present_symbols.add(normalized["symbol"])
        return universe

    def _fetch_cmc_quotes(self, symbols: list[str]) -> tuple[dict[str, dict], str]:
        if not self._coinmarketcap.is_configured:
            return {}, "NOT_IMPLEMENTED"
        try:
            quotes = self._coinmarketcap.fetch_quotes(symbols)
            return quotes, "OK"
        except Exception as exc:
            logger.warning("CoinMarketCap fetch failed: %s", exc)
            return {}, "UNAVAILABLE"

    def _safe_symbol_set(self, fetch_fn, source_name: str) -> tuple[set[str], str]:
        try:
            return fetch_fn(), "OK"
        except Exception as exc:
            logger.warning("%s listing fetch failed: %s", source_name, exc)
            return set(), "UNAVAILABLE"

    def _fetch_ohlcv(
        self, symbol: str, binance_symbols: set[str], coinbase_symbols: set[str]
    ) -> tuple[list[float], list[float], str]:
        if symbol in binance_symbols:
            try:
                rows = self._binance.fetch_daily_ohlcv(symbol, OHLCV_LOOKBACK_DAYS)
                if rows:
                    return [c for c, _v in rows], [v for _c, v in rows], "BINANCE"
            except Exception as exc:
                logger.warning("Binance OHLCV fetch failed for %s: %s", symbol, exc)

        if symbol in coinbase_symbols:
            try:
                rows = self._coinbase.fetch_daily_ohlcv(symbol, OHLCV_LOOKBACK_DAYS)
                if rows:
                    return [c for c, _v in rows], [v for _c, v in rows], "COINBASE"
            except Exception as exc:
                logger.warning("Coinbase OHLCV fetch failed for %s: %s", symbol, exc)

        return [], [], "UNAVAILABLE"

    def _log_price_disagreement(self, symbol: str, source_prices: dict[str, float | None], threshold: float = 0.02) -> None:
        present = {k: v for k, v in source_prices.items() if v is not None}
        if len(present) < 2:
            return
        values = list(present.values())
        spread = (max(values) - min(values)) / min(values) if min(values) > 0 else 0
        if spread > threshold:
            logger.info("%s: cross-source price disagreement %.2f%% — %s", symbol, spread * 100, present)

    def _get_held_assets(self) -> list[Asset]:
        """Phase 5b addendum: a real position (quantity > 0 in the
        append-only holdings_ledger) should never silently lose Judge
        coverage just because it falls out of today's top
        TOP_CANDIDATES_SIZE by composite score — previously an asset you
        hold could go a week or more with zero fresh Judge opinion (see
        doc/... TODO "Include currently-held assets in Judge coverage",
        now implemented rather than left declined). Returns full `Asset`
        rows, not just symbols (extended for `_merge_missing_held_assets`,
        which also needs each held asset's `coingecko_id`) — matched by
        symbol at the `_rank_and_tag_candidates` call site, not asset_id,
        since that method runs before `_promote_new_candidates` assigns
        `row.asset_id` for the day's rows.

        Phase 5o (2026-09-27): filtered through `filter_materially_held` --
        a dust position (years of tiny staking rewards, real examples
        found live worth $0.0000000000-$0.062) is a real position but not
        one worth spending real Judge/assessment cost deciding on every
        day; this closes exactly that gap."""
        aggregated = collapse_platforms(aggregate_current_holdings(self._holdings_ledger_repo.get_all_history()))
        price_by_asset_id = {}
        for entry in aggregated:
            if entry.asset_id is None:
                continue
            snapshot = self._snapshot_repo.get_latest_snapshot(entry.asset_id)
            if snapshot is not None:
                price_by_asset_id[entry.asset_id] = float(snapshot.price)
        material = filter_materially_held(aggregated, price_by_asset_id, self._settings.min_material_holding_usd)

        held_assets: list[Asset] = []
        for entry in material:
            if entry.asset_id is None:  # the cash line, not a real asset position
                continue
            asset = self._asset_repo.get_by_id(entry.asset_id)
            if asset:
                held_assets.append(asset)
        return held_assets

    def _rank_and_tag_candidates(self, rows: list[ScreenedAsset], held_symbols: set[str]) -> None:
        ranked = sorted(
            rows,
            key=lambda r: (r.composite_factor_score is None, -(r.composite_factor_score or 0)),
        )
        for rank, row in enumerate(ranked, start=1):
            row.rank = rank
            row.is_top_candidate = rank <= self._settings.top_candidates_size or row.symbol in held_symbols

        matched_held_symbols = {row.symbol for row in rows}
        for missing in held_symbols - matched_held_symbols:
            logger.warning(
                "Held asset %s wasn't in this run's screened universe at all, even after "
                "_merge_missing_held_assets' direct CoinGecko lookup (see that warning above) "
                "-- still gets no Judge coverage this run.",
                missing,
            )

    def _promote_new_candidates(self, rows: list[ScreenedAsset], run_id: str) -> list[str]:
        newly_promoted = []
        for row in rows:
            if not row.is_top_candidate:
                continue
            existing = self._asset_repo.get_by_coingecko_id(row.coingecko_id)
            if existing:
                row.asset_id = existing.id
                continue
            new_asset = self._asset_repo.create_asset(
                symbol=row.symbol,
                # Real bug fixed 2026-09-16, found live: this fell back to
                # the bare symbol (e.g. "ZEC" instead of "Zcash") for every
                # newly-promoted asset, even though CoinGecko's real display
                # name was already fetched in _build_universe and simply
                # never threaded through ScreenedAsset. `row.name` is that
                # real name now; the bare-symbol fallback stays only for the
                # genuine edge case where CoinGecko's response is missing it.
                name=row.name or row.symbol,
                coingecko_id=row.coingecko_id,
                coinmarketcap_id=row.coinmarketcap_id,
                active=True,
                in_asset=False,
            )
            row.asset_id = new_asset.id
            self._asset_status_repo.record_status_change(
                new_asset.id, "CANDIDATE", reason=f"Surfaced by screening run {run_id}"
            )
            newly_promoted.append(row.symbol)
        return newly_promoted

    def _classify_regime(
        self,
        run_id: str,
        now: datetime,
        universe: list[dict],
        factor_inputs: list[dict[str, float | None]],
        btc_entry: dict | None,
        btc_closes: list[float],
        momentum_90d_by_symbol: dict[str, float | None],
        btc_momentum_30d: float | None,
    ) -> MarketRegimeSnapshot:
        breadth_pct = compute_breadth_pct([f["momentum_30d"] for f in factor_inputs])
        ma7 = moving_average(btc_closes, 7) if btc_closes else None
        ma30 = moving_average(btc_closes, min(30, len(btc_closes))) if btc_closes else None

        regime = None
        if btc_closes and ma7 is not None and ma30 is not None:
            regime = classify_risk_regime(btc_closes[-1], ma7, ma30, breadth_pct)

        total_market_cap = sum(u["market_cap"] for u in universe if u.get("market_cap"))
        btc_dominance = (
            compute_btc_dominance(btc_entry["market_cap"], total_market_cap)
            if btc_entry and btc_entry.get("market_cap") and total_market_cap
            else None
        )

        btc_momentum_90d = momentum_90d_by_symbol.get("BTC")
        altcoin_momentum_90d = [
            v for symbol, v in momentum_90d_by_symbol.items() if symbol != "BTC"
        ]
        altcoin_season_index = compute_altcoin_season_index(altcoin_momentum_90d, btc_momentum_90d)

        days_since_halving, days_until_halving = compute_halving_cycle_days(now.date())

        inputs = {
            "btc_price": btc_closes[-1] if btc_closes else None,
            "btc_ma7": ma7,
            "btc_ma30": ma30,
            "breadth_pct": breadth_pct,
            "btc_dominance": btc_dominance,
            "altcoin_season_index": altcoin_season_index,
            "altcoin_season_index_available": btc_momentum_90d is not None,
            "days_since_halving": days_since_halving,
            "days_until_next_halving_estimated": days_until_halving,
        }

        return MarketRegimeSnapshot(
            run_id=run_id,
            computed_at=now,
            regime=regime,
            inputs=inputs,
            notes=(
                None
                if btc_momentum_90d is not None
                else "altcoin_season_index UNAVAILABLE: requires CoinMarketCap's 90d "
                "percent-change field (COINMARKETCAP_API_KEY not configured)"
            ),
        )
