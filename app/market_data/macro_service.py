import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from app.database.evidence_provenance import DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE
from app.database.repository import AssetRepository, EvidenceObservationRepository, SignalSourceRepository
from app.market_data.binance import BinanceClient
from app.market_data.congress_gov import CongressGovClient
from app.market_data.evidence_schemas import EvidenceObservation
from app.market_data.fred import FredClient
from app.market_data.sec_edgar import SecEdgarClient
from app.market_data.upbit import UpbitClient
from app.risk.correlation import compute_daily_returns, pearson_correlation

logger = logging.getLogger("crypto_ai_portfolio.market_data")

# Task 5: macro observations. FRED series_id -> (display title, evidence key).
# ADP employment and "Fed rate expectations" are deliberately excluded — ADP's
# report is a private ADP Research Institute product, not published via FRED;
# forward rate expectations need Fed-funds-futures pricing, not FRED data.
MACRO_SERIES: dict[str, tuple[str, str]] = {
    "CPIAUCSL": ("Consumer Price Index (all urban consumers)", "cpi"),
    "PCEPI": ("Personal Consumption Expenditures Price Index", "pce"),
    "ICSA": ("Initial Jobless Claims", "initial_claims"),
    "PAYEMS": ("Total Nonfarm Payrolls", "payrolls"),
    "DGS10": ("10-Year Treasury Constant Maturity Rate", "treasury_10y"),
    "FEDFUNDS": ("Effective Federal Funds Rate", "fed_funds"),
}

# Task 5a: forward-looking calendar. FRED release_id -> event key. FOMC
# (release_id 101, "FOMC Press Release") was checked live and does NOT behave
# as a discrete meeting calendar — it returns a release date for every single
# day, not ~8 meetings/year — so it's excluded here, not silently faked.
FORWARD_CALENDAR_RELEASES: dict[int, str] = {
    10: "CPI",
    54: "PCE",
    50: "NFP",
}
FORWARD_CALENDAR_HORIZON_DAYS = 120

# Task 5b: global liquidity proxies.
GLOBAL_LIQUIDITY_SERIES: dict[str, str] = {
    "M2SL": "m2",
    "WALCL": "fed_balance_sheet",
    "RRPONTSYD": "reverse_repo",
}

# Task 5b: BTC rolling correlation windows and reference series. Gold has no
# working FRED series any more (GOLDAMGBD228NLBM discontinued, verified
# live) — PAXG (tokenized gold) on Binance is used instead, a live-verified
# real price (~$4432/oz, matching Coinbase within cents), not a new vendor.
CORRELATION_WINDOWS_DAYS = (30, 90)
# FRED reference series (SP500/DTWEXBGS) only trade ~5 days/week — verified
# live that 100 calendar days only yields ~68 overlapping business days with
# BTC's 24/7 series, short of the 91 the 90d window needs. 150 comfortably
# covers ~107 business days even with holidays.
CORRELATION_HISTORY_DAYS = 150

# Regulatory calendar keyword filter — a naive keyword match, per
# PHASE3F_PROMPT.md's own acknowledgment of the false-positive/negative risk.
# Global/macro-scope only: reliable per-asset attribution isn't achievable at
# a reasonable false-positive rate for either source (a filing/bill can
# mention "bitcoin" incidentally, or the underlying instrument's economic
# effect on one specific tracked asset can't be inferred from a title alone).
REGULATORY_KEYWORDS = ("bitcoin", "cryptocurrency", "crypto asset", "digital asset", "stablecoin", "blockchain")


@dataclass
class MacroResult:
    macro_observations: list[str] = field(default_factory=list)
    forward_calendar_entries: int = 0
    global_liquidity_series: list[str] = field(default_factory=list)
    correlations_computed: list[str] = field(default_factory=list)
    regional_premium_computed: bool = False
    regulatory_events_found: int = 0
    source_status: dict[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        return (
            f"macro_observations={self.macro_observations} "
            f"forward_calendar_entries={self.forward_calendar_entries} "
            f"global_liquidity={self.global_liquidity_series} "
            f"correlations={self.correlations_computed} "
            f"regional_premium={self.regional_premium_computed} "
            f"regulatory_events={self.regulatory_events_found}"
        )


class MacroService:
    """3f tasks 5/5a/5b + the regional-exchange-premium and
    regulatory-event-calendar fragile sources. Zero LLM calls. Every raw
    observation is stored as-is (see PHASE3F_PROMPT.md's per-source
    interpretation constraints) — no directional signal derived here."""

    def __init__(
        self,
        asset_repo: AssetRepository,
        evidence_repo: EvidenceObservationRepository,
        signal_source_repo: SignalSourceRepository,
        fred_client: FredClient,
        upbit_client: UpbitClient,
        sec_edgar_client: SecEdgarClient,
        congress_gov_client: CongressGovClient,
        binance_client: BinanceClient,
    ) -> None:
        self._asset_repo = asset_repo
        self._evidence_repo = evidence_repo
        self._signal_source_repo = signal_source_repo
        self._fred = fred_client
        self._upbit = upbit_client
        self._sec_edgar = sec_edgar_client
        self._congress_gov = congress_gov_client
        self._binance = binance_client

    def run(self, run_id: str) -> MacroResult:
        result = MacroResult()
        now = datetime.now(UTC)
        observations: list[EvidenceObservation] = []

        if self._fred.is_configured:
            observations += self._collect_macro_observations(now, result)
            observations += self._collect_forward_calendar(now, result)
            observations += self._collect_global_liquidity(now, result)
            macro_status = "OK"
            liquidity_status = "OK" if result.global_liquidity_series else "UNAVAILABLE"
        else:
            macro_status = "NOT_IMPLEMENTED"
            liquidity_status = "NOT_IMPLEMENTED"

        # Not gated on FRED configuration: gold_paxg is Binance-sourced and
        # needs no FRED data at all; sp500/dxy independently degrade to
        # nothing (FredClient methods return [] when unconfigured) rather
        # than blocking gold_paxg too.
        observations += self._collect_correlations(now, result)

        observations += self._collect_regional_premium(now, result)

        regulatory_obs, regulatory_status = self._collect_regulatory_events(now, result)
        observations += regulatory_obs

        self._evidence_repo.insert_many(observations)

        result.source_status = {
            "Macro": macro_status,
            "GLOBAL_LIQUIDITY_MACRO": liquidity_status,
            "REGIONAL_EXCHANGE_PREMIUM": "OK" if result.regional_premium_computed else "UNAVAILABLE",
            "REGULATORY_EVENT_CALENDAR": regulatory_status,
            # Investigated in 3f, deliberately not built — reaffirmed with
            # real investigation notes every run, not left untouched since
            # their 3a seed (the exact gap a 3c live-verification incident
            # caught: a status never actually re-checked by code looks
            # identical, in a clean report, to one that genuinely was).
            "CryptoBubbles": "UNAVAILABLE",
            "CoinAnk": "UNAVAILABLE",
            "CoinGlass": "NOT_IMPLEMENTED",
            "PlanB": "NOT_IMPLEMENTED",
            "SOCIAL_NARRATIVE_SENTIMENT": "NOT_IMPLEMENTED",
        }
        notes = {
            "Macro": None if self._fred.is_configured else "FRED_API_KEY not configured.",
            "GLOBAL_LIQUIDITY_MACRO": None if self._fred.is_configured else "FRED_API_KEY not configured.",
            "REGULATORY_EVENT_CALENDAR": (
                "Global/macro-scope only (SEC EDGAR full-text search, no key needed; "
                "congress.gov bill titles, keyword-filtered client-side — no server-side "
                "full-text search available, verified live). Per-asset attribution not "
                "attempted: reliable extraction isn't achievable at an acceptable "
                "false-positive rate from a title/filing match alone."
            ),
            "CryptoBubbles": (
                "Investigated in 3f: no documented API found (a guessed data endpoint "
                "returned 404); robots.txt explicitly disallows ClaudeBot site-wide."
            ),
            "CoinAnk": (
                "Investigated in 3f: the site is behind a BytePlus WAF bot-challenge "
                "(a JS challenge page, no accessible endpoint or robots.txt) — no "
                "legitimate API surface exists to build against."
            ),
            "CoinGlass": (
                "Investigated in 3f: a real, official, documented API exists "
                "(docs.coinglass.com) but is API-key-gated with tiered paid plans "
                "(Startup/Standard/Professional); no usable free tier confirmed for "
                "liquidation-heatmap data. Same category as Glassnode in 3c — a real "
                "recurring-cost decision, deliberately deferred, not subscribed to."
            ),
            "PlanB": (
                "Investigated in 3f: xAI's API is live and functional (verified a real "
                "auth-challenge response), but deliberately not pursued — no paid API "
                "relationship established for this source at this time."
            ),
            "SOCIAL_NARRATIVE_SENTIMENT": (
                "Investigated in 3f: Santiment's anonymous free tier is genuinely "
                "accessible with no key (verified live: real social_volume_total data "
                "returned) but restricted to data at least ~30 days old — unusable for "
                "live current-sentiment reads, this system's actual use case. LunarCrush "
                "re-investigated 2026-09-15 with a real user-provided LUNARCRUSH_API_KEY "
                "(set in .env, not yet wired into Settings/any client): live-tested "
                "against /public/coins/list/v1, /public/coins/{symbol,id}/v1, and "
                "/public/topic/{topic}/v1 — every one returned HTTP 402 'You must have "
                "an active Individual or higher subscription to use this endpoint,' "
                "including the coins-list endpoint LunarCrush's own docs cite as their "
                "free-tier example. Same paid-tier deferral as CoinGlass/Glassnode — "
                "user chose not to upgrade for now."
            ),
        }
        for name, status in result.source_status.items():
            self._signal_source_repo.update_status(name, status, notes=notes.get(name))

        logger.info("Macro collection complete: %s", result.summary)
        return result

    def _collect_macro_observations(self, now: datetime, result: MacroResult) -> list[EvidenceObservation]:
        observations = []
        for series_id, (title, key) in MACRO_SERIES.items():
            try:
                obs = self._fred.fetch_recent_observations(series_id, limit=2)
            except Exception as exc:
                logger.warning("FRED fetch failed for %s: %s", series_id, exc)
                continue
            if len(obs) < 2:
                continue
            previous, latest = obs[-2], obs[-1]
            observations.append(EvidenceObservation(
                source=f"macro_{key}", asset_id=None, scope="MACRO",
                observation_timestamp=datetime.fromisoformat(latest["date"]).replace(tzinfo=UTC),
                publication_timestamp=None, retrieval_timestamp=now, timeframe=None, is_revision_of=None,
                freshness="RECENT",
                decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["macro"],
                status="OK",
                payload={
                    "series_id": series_id, "title": title,
                    "actual": latest["value"], "previous": previous["value"],
                    "observation_date": latest["date"],
                    # No free source for economist-consensus estimates was
                    # found/verified — never fabricated.
                    "consensus": None, "surprise": None,
                },
            ))
            result.macro_observations.append(key)
        return observations

    def _collect_forward_calendar(self, now: datetime, result: MacroResult) -> list[EvidenceObservation]:
        observations = []
        today = now.date().isoformat()
        horizon = (now + timedelta(days=FORWARD_CALENDAR_HORIZON_DAYS)).date().isoformat()
        for release_id, event_key in FORWARD_CALENDAR_RELEASES.items():
            try:
                dates = self._fred.fetch_release_dates(release_id, realtime_start=today)
            except Exception as exc:
                logger.warning("FRED release-dates fetch failed for release %s: %s", release_id, exc)
                continue
            future_dates = [d for d in dates if today <= d <= horizon]
            for d in future_dates:
                observations.append(EvidenceObservation(
                    source="scheduled_macro_event", asset_id=None, scope="MACRO",
                    observation_timestamp=datetime.fromisoformat(d).replace(tzinfo=UTC),
                    publication_timestamp=None, retrieval_timestamp=now, timeframe=None, is_revision_of=None,
                    freshness="UNKNOWN",  # a future date — "freshness" as a staleness concept doesn't apply
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["scheduled_macro_event"],
                    status="OK",
                    payload={"event": event_key, "scheduled_date": d},
                ))
                result.forward_calendar_entries += 1
        return observations

    def _collect_global_liquidity(self, now: datetime, result: MacroResult) -> list[EvidenceObservation]:
        observations = []
        for series_id, key in GLOBAL_LIQUIDITY_SERIES.items():
            try:
                obs = self._fred.fetch_latest_observation(series_id)
            except Exception as exc:
                logger.warning("FRED fetch failed for %s: %s", series_id, exc)
                continue
            if obs is None:
                continue
            observations.append(EvidenceObservation(
                source=f"global_liquidity_{key}", asset_id=None, scope="GLOBAL_CRYPTO",
                observation_timestamp=datetime.fromisoformat(obs["date"]).replace(tzinfo=UTC),
                publication_timestamp=None, retrieval_timestamp=now, timeframe=None, is_revision_of=None,
                freshness="RECENT",
                decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["global_liquidity"],
                status="OK",
                payload={"series_id": series_id, "value": obs["value"], "observation_date": obs["date"]},
            ))
            result.global_liquidity_series.append(key)
        return observations

    def _collect_correlations(self, now: datetime, result: MacroResult) -> list[EvidenceObservation]:
        observations = []
        btc_closes = self._fetch_binance_closes("BTC")
        if not btc_closes:
            return observations
        btc_dates = {d.date().isoformat(): c for d, c in btc_closes}

        reference_series = {
            "sp500": ("FRED", "SP500"),
            "gold_paxg": ("BINANCE", "PAXG"),
            "dxy": ("FRED", "DTWEXBGS"),
        }
        for key, (source_kind, series_id) in reference_series.items():
            try:
                ref_by_date = self._fetch_reference_series(source_kind, series_id)
            except Exception as exc:
                logger.warning("Correlation reference fetch failed for %s: %s", key, exc)
                continue
            if not ref_by_date:
                continue

            shared_dates = sorted(set(btc_dates) & set(ref_by_date))
            if len(shared_dates) < max(CORRELATION_WINDOWS_DAYS) + 1:
                continue
            btc_series = [btc_dates[d] for d in shared_dates]
            ref_series = [ref_by_date[d] for d in shared_dates]

            windows = {}
            for window in CORRELATION_WINDOWS_DAYS:
                btc_returns = compute_daily_returns(btc_series[-(window + 1):])
                ref_returns = compute_daily_returns(ref_series[-(window + 1):])
                corr = pearson_correlation(btc_returns, ref_returns)
                if corr is not None:
                    windows[f"{window}d"] = corr

            if not windows:
                continue
            observations.append(EvidenceObservation(
                source=f"btc_correlation_{key}", asset_id=None, scope="GLOBAL_CRYPTO",
                observation_timestamp=now, publication_timestamp=None, retrieval_timestamp=now,
                timeframe=None, is_revision_of=None, freshness="RECENT",
                decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["global_liquidity"],
                status="OK",
                payload={"reference": series_id, "windows": windows, "as_of": shared_dates[-1]},
            ))
            result.correlations_computed.append(key)
        return observations

    def _fetch_binance_closes(self, symbol: str) -> list[tuple[datetime, float]]:
        try:
            rows = self._binance.fetch_daily_ohlcv_with_timestamps(symbol, CORRELATION_HISTORY_DAYS)
        except Exception as exc:
            logger.warning("Binance historical fetch failed for %s: %s", symbol, exc)
            return []
        if not rows:
            return []
        return [(d, c) for d, c, _v in rows]

    def _fetch_reference_series(self, source_kind: str, series_id: str) -> dict[str, float]:
        if source_kind == "BINANCE":
            return {d.date().isoformat(): c for d, c in self._fetch_binance_closes(series_id)}
        # FRED
        obs = self._fred.fetch_recent_observations(series_id, limit=CORRELATION_HISTORY_DAYS)
        return {o["date"]: float(o["value"]) for o in obs}

    def _collect_regional_premium(self, now: datetime, result: MacroResult) -> list[EvidenceObservation]:
        try:
            krw_ticker = self._upbit.fetch_ticker("KRW-BTC")
        except Exception as exc:
            logger.warning("Upbit fetch failed: %s", exc)
            return []
        if krw_ticker is None:
            return []

        krw_price = krw_ticker.get("trade_price")
        if krw_price is None:
            return []

        try:
            fx = self._fred.fetch_latest_observation("DEXKOUS") if self._fred.is_configured else None
        except Exception as exc:
            logger.warning("FRED KRW/USD fetch failed: %s", exc)
            fx = None
        if fx is None:
            return []
        krw_per_usd = float(fx["value"])

        global_btc_series = self._fetch_binance_closes("BTC")
        if not global_btc_series:
            return []
        global_usd_price = global_btc_series[-1][1]

        korean_usd_price = krw_price / krw_per_usd
        premium_pct = (korean_usd_price / global_usd_price - 1) * 100

        result.regional_premium_computed = True
        return [EvidenceObservation(
            source="regional_exchange_premium_upbit", asset_id=None, scope="GLOBAL_CRYPTO",
            observation_timestamp=now, publication_timestamp=None, retrieval_timestamp=now,
            timeframe=None, is_revision_of=None, freshness="RECENT",
            decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["regional_exchange_premium"],
            status="OK",
            payload={
                "exchange": "Upbit", "market": "KRW-BTC", "krw_price": krw_price,
                "krw_per_usd_fx_date": fx["date"], "krw_per_usd": krw_per_usd,
                "implied_usd_price": korean_usd_price, "global_usd_price": global_usd_price,
                "premium_pct": premium_pct,
            },
        )]

    def _collect_regulatory_events(self, now: datetime, result: MacroResult) -> tuple[list[EvidenceObservation], str]:
        observations = []
        any_source_worked = False

        try:
            sec_hits = self._sec_edgar.search_full_text(
                query="bitcoin OR cryptocurrency OR digital asset",
                start_date=(now - timedelta(days=30)).date().isoformat(),
                end_date=now.date().isoformat(),
            )
            any_source_worked = True
        except Exception as exc:
            logger.warning("SEC EDGAR fetch failed: %s", exc)
            sec_hits = []
        for hit in sec_hits[:20]:
            file_date = hit.get("file_date")
            if not file_date:
                continue
            observations.append(EvidenceObservation(
                source="regulatory_event_sec_edgar", asset_id=None, scope="MACRO",
                observation_timestamp=datetime.fromisoformat(file_date).replace(tzinfo=UTC),
                publication_timestamp=None, retrieval_timestamp=now, timeframe=None, is_revision_of=None,
                freshness="RECENT",
                decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["regulatory_event"],
                status="OK",
                payload={
                    "form": hit.get("form"), "display_names": hit.get("display_names"),
                    "file_date": file_date, "accession_number": hit.get("adsh"),
                },
            ))
            result.regulatory_events_found += 1

        if self._congress_gov.is_configured:
            try:
                bills = self._congress_gov.fetch_recent_bills(
                    from_datetime=(now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    to_datetime=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                any_source_worked = True
            except Exception as exc:
                logger.warning("congress.gov fetch failed: %s", exc)
                bills = []
            for bill in bills:
                title = (bill.get("title") or "").lower()
                if not any(keyword in title for keyword in REGULATORY_KEYWORDS):
                    continue
                update_date = bill.get("updateDate")
                if not update_date:
                    continue
                observations.append(EvidenceObservation(
                    source="regulatory_event_congress", asset_id=None, scope="MACRO",
                    observation_timestamp=datetime.fromisoformat(update_date).replace(tzinfo=UTC),
                    publication_timestamp=None, retrieval_timestamp=now, timeframe=None, is_revision_of=None,
                    freshness="RECENT",
                    decay_half_life_hours=DECAY_HALF_LIFE_HOURS_BY_SOURCE_TYPE["regulatory_event"],
                    status="OK",
                    payload={
                        "title": bill.get("title"), "type": bill.get("type"), "number": bill.get("number"),
                        "congress": bill.get("congress"), "latest_action": bill.get("latestAction"),
                    },
                ))
                result.regulatory_events_found += 1

        status = "OK" if any_source_worked else "UNAVAILABLE"
        return observations, status
