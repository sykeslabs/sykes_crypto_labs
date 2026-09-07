"""Phase 5b: exposes `app/news/`'s collected articles read-only — this
data has existed since the news-ingestion pipeline was built (feeding the
Judge's research context internally) but was never reachable via the API
or shown anywhere on the dashboard until now, a real gap found while
reviewing what the dashboard does and doesn't surface.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from app.api.auth import verify_api_key
from app.api.dependencies import get_asset_repo, get_news_repo
from app.database.repository import AssetRepository, NewsRepository
from app.news.schemas import NewsArticle

router = APIRouter(prefix="/news", tags=["news"], dependencies=[Depends(verify_api_key)])

# NewsRepository.get_recent_relevant_news has no "unlimited" option -- its
# per-symbol cap is a required int, used elsewhere (app/judge/context.py,
# app/llm/*.py) to keep a real LLM prompt's size down, so that method's own
# contract is left untouched. When this endpoint's own `limit` is None (its
# default -- "all matching articles", not just the top 20), this large
# sentinel is passed as the per-symbol cap instead: high enough that no
# real per-symbol article count in the collected window would ever hit it.
_EFFECTIVELY_UNLIMITED_PER_SYMBOL_CAP = 10_000


@router.get("/recent", response_model=list[NewsArticle])
def get_recent_news(
    limit: int | None = None,
    days: int = 7,
    asset_repo: AssetRepository = Depends(get_asset_repo),
    news_repo: NewsRepository = Depends(get_news_repo),
) -> list[NewsArticle]:
    """Every article across every currently-active tracked asset published
    within the last `days` (default 7), newest first — `limit=None`
    (default) returns all of them, not just a top-20 slice; pass a real
    `limit` to cap the result if a caller wants that instead.
    `NewsArticle` is returned directly (no join view needed:
    `relevant_assets` already stores real symbols, per
    `app/news/relevance.py`, never raw asset ids). `NewsRepository` has no
    "all news, unfiltered" read method, only a per-symbol one
    (`get_recent_relevant_news`), so this calls it once per active symbol,
    merges, dedupes (an article relevant to multiple assets would
    otherwise appear once per symbol), and sorts by `published_at`. An
    asset with no active tracked symbols, or no news in the window,
    correctly returns `[]`, never an error."""
    symbols = [asset.symbol for asset in asset_repo.get_active_assets()]
    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    per_symbol_cap = limit if limit is not None else _EFFECTIVELY_UNLIMITED_PER_SYMBOL_CAP
    by_symbol = news_repo.get_recent_relevant_news(symbols, since, until, limit_per_asset=per_symbol_cap)

    seen: set[str] = set()
    articles: list[NewsArticle] = []
    for symbol_articles in by_symbol.values():
        for article in symbol_articles:
            key = article.id or article.content_hash
            if key not in seen:
                seen.add(key)
                articles.append(article)

    articles.sort(key=lambda a: a.published_at, reverse=True)
    return articles if limit is None else articles[:limit]
