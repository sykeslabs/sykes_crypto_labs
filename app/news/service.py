import logging
import re
from dataclasses import dataclass

from app.database.repository import AssetRepository, NewsRepository
from app.news.relevance import match_assets
from app.news.rss_client import RssClient, parse_pub_date
from app.news.schemas import NewsArticle

logger = logging.getLogger("crypto_ai_portfolio.news")

MAX_SUMMARY_LENGTH = 500


@dataclass
class NewsCollectionResult:
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_irrelevant: int = 0
    skipped_no_date: int = 0

    @property
    def summary(self) -> str:
        return (
            f"inserted={self.inserted} "
            f"skipped_duplicate={self.skipped_duplicate} "
            f"skipped_irrelevant={self.skipped_irrelevant} "
            f"skipped_no_date={self.skipped_no_date}"
        )


class NewsCollectionService:
    """Fetches recent crypto news, matches it against the active asset
    universe, and persists only new, relevant articles."""

    def __init__(
        self,
        asset_repo: AssetRepository,
        news_repo: NewsRepository,
        rss_client: RssClient,
    ) -> None:
        self._asset_repo = asset_repo
        self._news_repo = news_repo
        self._rss_client = rss_client

    def run(self) -> NewsCollectionResult:
        result = NewsCollectionResult()

        assets = self._asset_repo.get_active_assets()
        if not assets:
            logger.warning("No active assets found — skipping news collection.")
            return result

        entries = self._rss_client.fetch_all()
        logger.info("Fetched %d raw news entries across all feeds.", len(entries))

        candidates = []
        for entry in entries:
            published_at = parse_pub_date(entry.published_at_raw)
            if published_at is None:
                result.skipped_no_date += 1
                continue

            summary = _clean_summary(entry.summary)
            relevant = match_assets(f"{entry.title} {summary or ''}", assets)
            if not relevant:
                result.skipped_irrelevant += 1
                continue

            candidates.append(_build_article(entry, published_at, summary, relevant))

        if not candidates:
            logger.info("News collection complete: %s", result.summary)
            return result

        hashes = [article.content_hash for article in candidates]
        existing_hashes = self._news_repo.get_existing_hashes(hashes)
        new_articles = [a for a in candidates if a.content_hash not in existing_hashes]
        result.skipped_duplicate = len(candidates) - len(new_articles)

        if new_articles:
            self._news_repo.insert_articles(new_articles)
            result.inserted = len(new_articles)

        logger.info("News collection complete: %s", result.summary)
        return result


def _build_article(entry, published_at, summary, relevant_assets):
    return NewsArticle(
        published_at=published_at,
        source=entry.source,
        title=entry.title,
        url=entry.url,
        summary=summary,
        relevant_assets=relevant_assets,
    )


def _clean_summary(raw: str | None) -> str | None:
    if not raw:
        return None
    text = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:MAX_SUMMARY_LENGTH]
