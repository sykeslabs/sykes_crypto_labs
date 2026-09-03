import sys

from app.config import get_settings
from app.database.client import get_supabase_client
from app.database.repository import AssetRepository, MarketSnapshotRepository
from app.logging_config import new_run_id, setup_logging
from app.market_data.coingecko import CoinGeckoClient
from app.market_data.service import MarketDataCollectionService


def main() -> int:
    settings = get_settings()
    run_id = new_run_id()
    logger = setup_logging(run_id, settings.log_level)

    logger.info("Starting market data collection run")

    try:
        client = get_supabase_client()
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    service = MarketDataCollectionService(
        settings=settings,
        asset_repo=AssetRepository(client),
        snapshot_repo=MarketSnapshotRepository(client),
        coingecko_client=CoinGeckoClient(settings),
    )

    result = service.run()

    logger.info("Run finished: %s", result.summary)
    if result.inserted:
        logger.info("Inserted snapshots for: %s", ", ".join(result.inserted))
    if result.failed:
        logger.warning("Failures: %s", result.failed)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
