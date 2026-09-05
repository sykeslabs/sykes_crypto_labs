import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.database.evidence_provenance import DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE
from app.database.models import Asset
from app.database.repository import (
    AssetRepository,
    EvidenceObservationRepository,
    ScreenedUniverseRepository,
    SignalSourceRepository,
)
from app.market_data.binance import BinanceClient
from app.market_data.cftc import CftcClient
from app.market_data.defillama import DefiLlamaClient
from app.market_data.derivatives_factors import (
    annualize_daily_volatility,
    compute_annualized_carry_yield,
    compute_volatility_risk_premium,
)
from app.market_data.deribit import DeribitClient
from app.market_data.etherscan import EtherscanClient
from app.market_data.evidence_schemas import EvidenceObservation
from app.market_data.glassnode import GlassnodeClient

logger = logging.getLogger("crypto_ai_portfolio.market_data")

# Verified live (see PHASE3C completion notes): Deribit options and dated
# futures exist ONLY for these two assets among the whole tracked universe.
DEEP_DERIVATIVES_SYMBOLS = ("BTC", "ETH")

# Native ETH transfers observed via the Etherscan proxy are attributed to
# ETH's own evidence record — this is Ethereum-network activity, not a
# statement about any specific ERC20 token.
ETHERSCAN_TARGET_SYMBOL = "ETH"


@dataclass
class DerivativesResult:
    funding_rate_assets: list[str] = field(default_factory=list)
    deep_derivatives_assets: list[str] = field(default_factory=list)
    tvl_matches: list[str] = field(default_factory=list)
    stablecoins_captured: int = 0
    etherscan_captured: bool = False
    source_status: dict[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return (
            f"funding_rate_assets={self.funding_rate_assets} "
            f"deep_derivatives={self.deep_derivatives_assets} "
            f"tvl_matches={self.tvl_matches} "
            f"stablecoins={self.stablecoins_captured} "
            f"etherscan={self.etherscan_captured}"
        )


class DerivativesService:
    """3c: derivatives (funding, open interest, term structure/carry yield,
    options + VRP, CME COT positioning) and on-chain/DeFi evidence
    (DefiLlama TVL, stablecoin supply, Etherscan large-transfer proxy,
    Glassnode on-chain valuation metrics). Zero LLM calls. Every raw
    observation is stored as-is — no directional signal is derived at the
    collector level (see per-source interpretation constraints in
    PHASE3C_PROMPT.md)."""

    def __init__(
        self,
        asset_repo: AssetRepository,
        evidence_repo: EvidenceObservationRepository,
        screened_universe_repo: ScreenedUniverseRepository,
        signal_source_repo: SignalSourceRepository,
        binance_client: BinanceClient,
        deribit_client: DeribitClient,
        cftc_client: CftcClient,
        defillama_client: DefiLlamaClient,
        etherscan_client: EtherscanClient,
        glassnode_client: GlassnodeClient,
    ) -> None:
        self._asset_repo = asset_repo
        self._evidence_repo = evidence_repo
        self._screened_universe_repo = screened_universe_repo
        self._signal_source_repo = signal_source_repo
        self._binance = binance_client
        self._deribit = deribit_client
        self._cftc = cftc_client
        self._defillama = defillama_client
        self._etherscan = etherscan_client
        self._glassnode = glassnode_client

    def run(self, run_id: str) -> DerivativesResult:
        result = DerivativesResult()
        now = datetime.now(UTC)
        assets = self._asset_repo.get_active_assets()
        by_symbol = {a.symbol: a for a in assets}

        observations: list[EvidenceObservation] = []

        perp_symbols, binance_status = self._safe(self._binance.list_perpetual_symbols, "Binance perpetuals")
        for asset in assets:
            if asset.symbol in perp_symbols:
                observations.extend(self._collect_binance_funding_oi(asset, now))
                result.funding_rate_assets.append(asset.symbol)

        for symbol in DEEP_DERIVATIVES_SYMBOLS:
            asset = by_symbol.get(symbol)
            if asset is None:
                continue
            observations.extend(self._collect_deep_derivatives(asset, now))
            result.deep_derivatives_assets.append(symbol)

        cot_status = "OK"
        for symbol in DEEP_DERIVATIVES_SYMBOLS:
            asset = by_symbol.get(symbol)
            if asset is None:
                continue
            obs, ok = self._collect_cftc_cot(asset, now)
            if obs:
                observations.append(obs)
            cot_status = "OK" if ok else "UNAVAILABLE"

        tvl_status = "OK"
        try:
            protocols = self._defillama.fetch_protocols()
            for asset in assets:
                match = self._defillama.find_protocol_by_symbol(asset.symbol, protocols)
                if match is None:
                    continue
                observations.append(self._build_tvl_observation(asset, match, now))
                result.tvl_matches.append(asset.symbol)
        except Exception as exc:
            logger.warning("DefiLlama protocol fetch failed: %s", exc)
            tvl_status = "UNAVAILABLE"

        stablecoin_status = "OK"
        try:
            stablecoins = self._defillama.fetch_stablecoins()
            for sc in sorted(stablecoins, key=lambda s: s.get("circulating", {}).get("peggedUSD", 0) or 0, reverse=True)[:5]:
                observations.append(self._build_stablecoin_observation(sc, now))
                result.stablecoins_captured += 1
        except Exception as exc:
            logger.warning("DefiLlama stablecoins fetch failed: %s", exc)
            stablecoin_status = "UNAVAILABLE"

        etherscan_status = "NOT_IMPLEMENTED"
        if self._etherscan.is_configured:
            try:
                count = self._etherscan.count_large_transfers_last_24h()
                eth_asset = by_symbol.get(ETHERSCAN_TARGET_SYMBOL)
                if count is not None and eth_asset is not None:
                    observations.append(self._build_etherscan_observation(eth_asset, count, now))
                    result.etherscan_captured = True
                etherscan_status = "OK"
            except Exception as exc:
                logger.warning("Etherscan fetch failed: %s", exc)
                etherscan_status = "UNAVAILABLE"

        glassnode_status = "OK" if self._glassnode.is_configured else "NOT_IMPLEMENTED"

        self._evidence_repo.insert_many(observations)

        result.source_status = {
            "Binance": binance_status,
            "Deribit": "OK" if result.deep_derivatives_assets else "UNAVAILABLE",
            "AGGREGATE_OPEN_INTEREST": binance_status,
            "FUTURES_TERM_STRUCTURE": "OK" if result.deep_derivatives_assets else "UNAVAILABLE",
            "CME_COT_POSITIONING": cot_status,
            "DefiLlama": tvl_status,
            "STABLECOIN_SUPPLY_VELOCITY_AND_EXCHANGE_RESERVES": stablecoin_status,
            "Etherscan": etherscan_status,
            "ON_CHAIN_VALUATION_METRICS": glassnode_status,
            "ON_CHAIN_MINER_METRICS": glassnode_status,
            # Investigated this sub-phase and confirmed genuinely inaccessible
            # (see README "Phase 3c" section) — reaffirmed here, not just left
            # as whatever 3a originally seeded, so `last_checked_at`/`notes`
            # actually reflect this sub-phase's real findings.
            "SPOT_ETF_FLOWS": "NOT_IMPLEMENTED",
            "TOKEN_UNLOCK_SCHEDULE": "NOT_IMPLEMENTED",
            "PREDICTION_MARKETS": "NOT_IMPLEMENTED",
        }
        source_notes = {
            "SPOT_ETF_FLOWS": (
                "Investigated in 3c: Farside has no real API (Cloudflare-"
                "protected webpage only); SoSoValue's API requires an "
                "authenticated login not available here. Revisit if SoSoValue "
                "API access is obtained."
            ),
            "TOKEN_UNLOCK_SCHEDULE": (
                "Investigated in 3c: Messari requires an API key not available "
                "here (and its tier's unlock-data coverage is unconfirmed); "
                "TokenUnlocks.app has no discoverable public API. Revisit if a "
                "Messari key is obtained."
            ),
            "PREDICTION_MARKETS": (
                "Investigated in 3c: both Polymarket and Kalshi failed DNS "
                "resolution from this development sandbox specifically "
                "(confirmed general connectivity was fine). Revisit from an "
                "environment that can reach them."
            ),
        }
        for name, status in result.source_status.items():
            self._signal_source_repo.update_status(name, status, notes=source_notes.get(name))

        logger.info("Derivatives/on-chain collection complete: %s", result.summary)
        return result

    def _safe(self, fetch_fn, label: str):
        try:
            return fetch_fn(), "OK"
        except Exception as exc:
            logger.warning("%s fetch failed: %s", label, exc)
            return set(), "UNAVAILABLE"

    def _collect_binance_funding_oi(self, asset: Asset, now: datetime) -> list[EvidenceObservation]:
        observations = []
        try:
            funding = self._binance.fetch_funding_rate(asset.symbol)
            if funding:
                observations.append(EvidenceObservation(
                    source="binance_funding_rate",
                    asset_id=asset.id,
                    scope="ASSET",
                    observation_timestamp=now,
                    retrieval_timestamp=now,
                    timeframe="8h",
                    freshness="REALTIME",
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["binance_funding_rate"],
                    status="OK",
                    payload={
                        "funding_rate": funding["lastFundingRate"],
                        "next_funding_time": funding["nextFundingTime"],
                        "mark_price": funding["markPrice"],
                    },
                ))
        except Exception as exc:
            logger.warning("Binance funding rate failed for %s: %s", asset.symbol, exc)

        try:
            oi = self._binance.fetch_open_interest(asset.symbol)
            if oi is not None:
                observations.append(EvidenceObservation(
                    source="binance_open_interest",
                    asset_id=asset.id,
                    scope="ASSET",
                    observation_timestamp=now,
                    retrieval_timestamp=now,
                    freshness="RECENT",
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["open_interest"],
                    status="OK",
                    payload={"open_interest": oi},
                ))
        except Exception as exc:
            logger.warning("Binance open interest failed for %s: %s", asset.symbol, exc)

        return observations

    def _collect_deep_derivatives(self, asset: Asset, now: datetime) -> list[EvidenceObservation]:
        observations = []
        spot_price = None
        try:
            ticker = self._binance.fetch_ticker_24hr(asset.symbol)
            spot_price = float(ticker["lastPrice"]) if ticker else None
        except Exception as exc:
            logger.warning("Binance spot ticker failed for %s: %s", asset.symbol, exc)

        # Binance dated futures -> term structure / annualized carry yield
        try:
            for dated in self._binance.list_dated_futures(asset.symbol):
                price = self._binance.fetch_futures_price(dated["symbol"])
                if price is None or spot_price is None:
                    continue
                carry = compute_annualized_carry_yield(spot_price, price, dated["delivery_date"], now)
                observations.append(EvidenceObservation(
                    source="binance_futures_term_structure",
                    asset_id=asset.id,
                    scope="ASSET",
                    observation_timestamp=now,
                    retrieval_timestamp=now,
                    timeframe=dated["symbol"],
                    freshness="RECENT",
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["futures_term_structure"],
                    status="OK",
                    payload={
                        "instrument": dated["symbol"],
                        "spot_price": spot_price,
                        "futures_price": price,
                        "raw_basis": (price / spot_price) - 1 if spot_price else None,
                        "annualized_carry_yield": carry,
                    },
                ))
        except Exception as exc:
            logger.warning("Binance dated futures failed for %s: %s", asset.symbol, exc)

        # Deribit: OI, options IV + put/call, dated futures term structure, VRP
        implied_vol = None
        try:
            oi_by_instrument = self._deribit.fetch_futures_open_interest(asset.symbol)
            if oi_by_instrument:
                observations.append(EvidenceObservation(
                    source="deribit_open_interest",
                    asset_id=asset.id,
                    scope="ASSET",
                    observation_timestamp=now,
                    retrieval_timestamp=now,
                    freshness="RECENT",
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["open_interest"],
                    status="OK",
                    payload={"open_interest_by_instrument": oi_by_instrument},
                ))
        except Exception as exc:
            logger.warning("Deribit open interest failed for %s: %s", asset.symbol, exc)

        try:
            if spot_price is not None:
                option = self._deribit.find_near_atm_option(asset.symbol, spot_price)
                put_call_ratio = self._deribit.fetch_options_put_call_oi_ratio(asset.symbol)
                if option is not None:
                    ticker = self._deribit.fetch_ticker(option["instrument_name"])
                    implied_vol = ticker.get("mark_iv") if ticker else None
                    observations.append(EvidenceObservation(
                        source="deribit_options_iv",
                        asset_id=asset.id,
                        scope="ASSET",
                        observation_timestamp=now,
                        retrieval_timestamp=now,
                        timeframe=option["instrument_name"],
                        freshness="RECENT",
                        decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["options_data"],
                        status="OK",
                        payload={
                            "instrument": option["instrument_name"],
                            "mark_iv": implied_vol,
                            "put_call_oi_ratio": put_call_ratio,
                        },
                    ))
        except Exception as exc:
            logger.warning("Deribit options failed for %s: %s", asset.symbol, exc)

        try:
            for dated in self._deribit.list_dated_futures(asset.symbol):
                if spot_price is None:
                    continue
                ticker = self._deribit.fetch_ticker(dated["instrument_name"])
                price = ticker.get("mark_price") if ticker else None
                if price is None:
                    continue
                carry = compute_annualized_carry_yield(
                    spot_price, price, dated["expiration_timestamp"], now
                )
                observations.append(EvidenceObservation(
                    source="deribit_futures_term_structure",
                    asset_id=asset.id,
                    scope="ASSET",
                    observation_timestamp=now,
                    retrieval_timestamp=now,
                    timeframe=dated["instrument_name"],
                    freshness="RECENT",
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["futures_term_structure"],
                    status="OK",
                    payload={
                        "instrument": dated["instrument_name"],
                        "spot_price": spot_price,
                        "futures_price": price,
                        "raw_basis": (price / spot_price) - 1 if spot_price else None,
                        "annualized_carry_yield": carry,
                    },
                ))
        except Exception as exc:
            logger.warning("Deribit dated futures failed for %s: %s", asset.symbol, exc)

        # VRP: pair Deribit's annualized IV with 3b's realized volatility,
        # annualized to match scale. Only if both are genuinely available.
        try:
            realized_period_stdev = self._screened_universe_repo.get_latest_volatility(asset.symbol)
            realized_annualized = (
                annualize_daily_volatility(realized_period_stdev)
                if realized_period_stdev is not None
                else None
            )
            vrp = compute_volatility_risk_premium(implied_vol, realized_annualized)
            if vrp is not None:
                observations.append(EvidenceObservation(
                    source="volatility_risk_premium",
                    asset_id=asset.id,
                    scope="ASSET",
                    observation_timestamp=now,
                    retrieval_timestamp=now,
                    freshness="RECENT",
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["volatility_risk_premium"],
                    status="OK",
                    payload={
                        "implied_vol_annualized": implied_vol,
                        "realized_vol_annualized": realized_annualized,
                        "vrp": vrp,
                    },
                ))
        except Exception as exc:
            logger.warning("VRP computation failed for %s: %s", asset.symbol, exc)

        return observations

    def _collect_cftc_cot(self, asset: Asset, now: datetime) -> tuple[EvidenceObservation | None, bool]:
        try:
            report = self._cftc.fetch_latest_report(asset.symbol)
        except Exception as exc:
            logger.warning("CFTC COT fetch failed for %s: %s", asset.symbol, exc)
            return None, False

        if report is None:
            return None, False

        report_date = datetime.fromisoformat(report["report_date_as_yyyy_mm_dd"]).replace(tzinfo=UTC)
        observation = EvidenceObservation(
            source="cftc_cot",
            asset_id=asset.id,
            scope="ASSET",
            observation_timestamp=report_date,
            publication_timestamp=report_date,
            retrieval_timestamp=now,
            timeframe="weekly",
            freshness="STALE",  # by design — weekly report, several days lagged
            decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["cftc_cot"],
            status="OK",
            payload={
                "open_interest_all": report.get("open_interest_all"),
                "dealer_long": report.get("dealer_positions_long_all"),
                "dealer_short": report.get("dealer_positions_short_all"),
                "asset_mgr_long": report.get("asset_mgr_positions_long"),
                "asset_mgr_short": report.get("asset_mgr_positions_short"),
                "lev_money_long": report.get("lev_money_positions_long"),
                "lev_money_short": report.get("lev_money_positions_short"),
                "other_rept_long": report.get("other_rept_positions_long"),
                "other_rept_short": report.get("other_rept_positions_short"),
            },
        )
        return observation, True

    def _build_tvl_observation(self, asset: Asset, protocol: dict, now: datetime) -> EvidenceObservation:
        return EvidenceObservation(
            source="defillama_tvl",
            asset_id=asset.id,
            scope="ASSET",
            observation_timestamp=now,
            retrieval_timestamp=now,
            freshness="RECENT",
            decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["defillama_tvl"],
            status="OK",
            payload={
                "protocol": protocol.get("name"),
                "tvl": protocol.get("tvl"),
                "change_1d": protocol.get("change_1d"),
                "change_7d": protocol.get("change_7d"),
            },
        )

    def _build_stablecoin_observation(self, stablecoin: dict, now: datetime) -> EvidenceObservation:
        circulating = stablecoin.get("circulating", {}).get("peggedUSD")
        prev_week = stablecoin.get("circulatingPrevWeek", {}).get("peggedUSD")
        prev_month = stablecoin.get("circulatingPrevMonth", {}).get("peggedUSD")
        growth_7d = (circulating / prev_week - 1) if circulating and prev_week else None
        growth_30d = (circulating / prev_month - 1) if circulating and prev_month else None
        return EvidenceObservation(
            source="defillama_stablecoin_supply",
            asset_id=None,
            scope="GLOBAL_CRYPTO",
            observation_timestamp=now,
            retrieval_timestamp=now,
            freshness="RECENT",
            decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["stablecoin_supply"],
            status="OK",
            payload={
                "name": stablecoin.get("name"),
                "symbol": stablecoin.get("symbol"),
                "circulating_usd": circulating,
                "growth_7d": growth_7d,
                "growth_30d": growth_30d,
            },
        )

    def _build_etherscan_observation(self, eth_asset: Asset, count: int, now: datetime) -> EvidenceObservation:
        return EvidenceObservation(
            source="etherscan_large_transfer_count",
            asset_id=eth_asset.id,
            scope="ASSET",
            observation_timestamp=now,
            retrieval_timestamp=now,
            timeframe="24h",
            freshness="RECENT",
            decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["etherscan_large_transfer"],
            status="OK",
            payload={
                "large_transfer_count_24h": count,
                "limitation": (
                    "Raw count to/from a handful of known exchange addresses, "
                    "not entity-clustered — conflates genuine whale activity "
                    "with routine exchange-internal/protocol traffic."
                ),
            },
        )
