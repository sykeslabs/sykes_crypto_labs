import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.config import Settings
from app.database.models import Asset
from app.database.repository import AssetRepository, MarketSnapshotRepository
from app.market_data.coingecko import CoinGeckoClient
from app.market_data.normalize import normalize_coingecko_entry

logger = logging.getLogger("crypto_ai_portfolio.market_data")


@dataclass
class CollectionResult:
    inserted: list[str] = field(default_factory=list)
    skipped_duplicate: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"inserted={len(self.inserted)} "
            f"skipped_duplicate={len(self.skipped_duplicate)} "
            f"failed={len(self.failed)}"
        )


class MarketDataCollectionService:
    """Fetches current market data for the configured asset universe and
    persists deduplicated snapshots to Supabase."""

    def __init__(
        self,
        settings: Settings,
        asset_repo: AssetRepository,
        snapshot_repo: MarketSnapshotRepository,
        coingecko_client: CoinGeckoClient,
    ) -> None:
        self._settings = settings
        self._asset_repo = asset_repo
        self._snapshot_repo = snapshot_repo
        self._coingecko = coingecko_client

    def run(self) -> CollectionResult:
        result = CollectionResult()

        assets = self._asset_repo.get_active_assets()
        if not assets:
            logger.warning("No active assets found in the 'assets' table — nothing to collect.")
            return result

        logger.info("Collecting market data for %d active asset(s): %s",
                     len(assets), ", ".join(a.symbol for a in assets))

        try:
            markets = self._coingecko.fetch_markets([a.coingecko_id for a in assets])
        except Exception as exc:  # network/API failure must not crash the whole run
            logger.error("CoinGecko fetch failed: %s", exc)
            for asset in assets:
                result.failed.append((asset.symbol, str(exc)))
            return result

        for asset in assets:
            self._process_asset(asset, markets, result)

        logger.info("Market data collection complete: %s", result.summary)
        return result

    def _process_asset(self, asset: Asset, markets: dict, result: CollectionResult) -> None:
        entry = markets.get(asset.coingecko_id)
        if entry is None:
            msg = f"No CoinGecko data returned for '{asset.coingecko_id}'"
            logger.warning("%s (%s)", msg, asset.symbol)
            result.failed.append((asset.symbol, msg))
            return

        try:
            snapshot = normalize_coingecko_entry(asset.id, entry)
        except ValueError as exc:
            logger.warning("Failed to normalize data for %s: %s", asset.symbol, exc)
            result.failed.append((asset.symbol, str(exc)))
            return

        if self._is_duplicate(asset, snapshot.timestamp):
            logger.info("Skipping %s: snapshot within dedup interval", asset.symbol)
            result.skipped_duplicate.append(asset.symbol)
            return

        try:
            self._snapshot_repo.insert_snapshot(snapshot)
        except Exception as exc:
            logger.error("Failed to store snapshot for %s: %s", asset.symbol, exc)
            result.failed.append((asset.symbol, str(exc)))
            return

        logger.info("Stored snapshot for %s: price=%s", asset.symbol, snapshot.price)
        result.inserted.append(asset.symbol)

    def _is_duplicate(self, asset: Asset, new_timestamp: datetime) -> bool:
        latest = self._snapshot_repo.get_latest_snapshot_timestamp(asset.id)
        if latest is None:
            return False
        min_interval = timedelta(minutes=self._settings.min_snapshot_interval_minutes)
        return (new_timestamp - latest) < min_interval and new_timestamp >= latest
