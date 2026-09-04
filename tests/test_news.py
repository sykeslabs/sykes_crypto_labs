from datetime import UTC, datetime

from app.database.models import Asset
from app.news.relevance import match_assets
from app.news.rss_client import RawFeedEntry, parse_pub_date
from app.news.schemas import NewsArticle
from app.news.service import NewsCollectionService, _clean_summary


def _asset(symbol, name, coingecko_id=None, in_asset=True):
    return Asset(
        id=f"id-{symbol}",
        symbol=symbol,
        name=name,
        coingecko_id=coingecko_id or symbol.lower(),
        active=True,
        in_asset=in_asset,
        created_at=datetime.now(UTC),
    )


ASSETS = [
    _asset("BTC", "Bitcoin"),
    _asset("S", "Sonic"),
    _asset("ZRX", "0x Protocol"),
    _asset("ENA", "Ethena"),
]


def test_match_assets_by_name():
    matched = match_assets("Bitcoin rallies past $80k as ETF inflows surge", ASSETS)
    assert matched == ["BTC"]


def test_match_assets_by_symbol_when_long_enough():
    matched = match_assets("ENA token unlocks next week", ASSETS)
    assert matched == ["ENA"]


def test_short_symbol_alone_never_matches():
    # "S" is Sonic's ticker but far too short/common to match as a bare word.
    matched = match_assets("This is a sentence with the letter s in it", ASSETS)
    assert matched == []


def test_short_symbol_asset_matches_via_full_name():
    matched = match_assets("Sonic Labs announces new partnership", ASSETS)
    assert matched == ["S"]


def test_no_match_returns_empty_list():
    matched = match_assets("Completely unrelated article about weather", ASSETS)
    assert matched == []


def test_match_is_word_bounded_not_substring():
    # "ena" should not match inside an unrelated longer word like "arena".
    matched = match_assets("The team gathered at the arena for the event", ASSETS)
    assert matched == []


def test_content_hash_deterministic_and_unique():
    a1 = NewsArticle(
        published_at=datetime.now(UTC), source="Test", title="Same title", url="https://a.example/1"
    )
    a2 = NewsArticle(
        published_at=datetime.now(UTC), source="Test", title="Same title", url="https://a.example/1"
    )
    a3 = NewsArticle(
        published_at=datetime.now(UTC), source="Test", title="Different title", url="https://a.example/1"
    )
    assert a1.content_hash == a2.content_hash
    assert a1.content_hash != a3.content_hash


def test_parse_pub_date_valid_rfc822():
    dt = parse_pub_date("Wed, 03 Sep 2026 12:00:00 +0000")
    assert dt == datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)


def test_parse_pub_date_invalid_returns_none():
    assert parse_pub_date("not a date") is None
    assert parse_pub_date(None) is None


def test_clean_summary_strips_html_and_truncates():
    raw = "<p>Hello <b>world</b></p>" + ("x" * 600)
    cleaned = _clean_summary(raw)
    assert "<" not in cleaned
    assert len(cleaned) <= 500


def test_clean_summary_none_stays_none():
    assert _clean_summary(None) is None
    assert _clean_summary("   ") is None


class FakeAssetRepository:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeNewsRepository:
    def __init__(self, existing_hashes=None):
        self._existing = existing_hashes or set()
        self.inserted = []

    def get_existing_hashes(self, hashes):
        return {h for h in hashes if h in self._existing}

    def insert_articles(self, articles):
        self.inserted.extend(articles)


class FakeRssClient:
    def __init__(self, entries):
        self._entries = entries

    def fetch_all(self):
        return self._entries


def test_service_inserts_relevant_new_articles():
    entries = [
        RawFeedEntry(
            source="Test", title="Bitcoin surges", url="https://x/1",
            summary="BTC price action", published_at_raw="Wed, 03 Sep 2026 12:00:00 +0000",
        ),
        RawFeedEntry(
            source="Test", title="Weather report", url="https://x/2",
            summary="Sunny today", published_at_raw="Wed, 03 Sep 2026 12:00:00 +0000",
        ),
    ]
    news_repo = FakeNewsRepository()
    service = NewsCollectionService(
        asset_repo=FakeAssetRepository(ASSETS),
        news_repo=news_repo,
        rss_client=FakeRssClient(entries),
    )

    result = service.run()

    assert result.inserted == 1
    assert result.skipped_irrelevant == 1
    assert len(news_repo.inserted) == 1
    assert news_repo.inserted[0].title == "Bitcoin surges"


def test_service_skips_duplicates():
    entries = [
        RawFeedEntry(
            source="Test", title="Bitcoin surges", url="https://x/1",
            summary="BTC price action", published_at_raw="Wed, 03 Sep 2026 12:00:00 +0000",
        ),
    ]
    dup_hash = NewsArticle(
        published_at=datetime.now(UTC), source="Test", title="Bitcoin surges", url="https://x/1"
    ).content_hash
    news_repo = FakeNewsRepository(existing_hashes={dup_hash})
    service = NewsCollectionService(
        asset_repo=FakeAssetRepository(ASSETS),
        news_repo=news_repo,
        rss_client=FakeRssClient(entries),
    )

    result = service.run()

    assert result.inserted == 0
    assert result.skipped_duplicate == 1
    assert news_repo.inserted == []


def test_service_skips_entries_without_parseable_date():
    entries = [
        RawFeedEntry(
            source="Test", title="Bitcoin surges", url="https://x/1",
            summary="BTC price action", published_at_raw=None,
        ),
    ]
    service = NewsCollectionService(
        asset_repo=FakeAssetRepository(ASSETS),
        news_repo=FakeNewsRepository(),
        rss_client=FakeRssClient(entries),
    )

    result = service.run()

    assert result.skipped_no_date == 1
    assert result.inserted == 0


def test_service_no_active_assets_returns_empty_result():
    service = NewsCollectionService(
        asset_repo=FakeAssetRepository([]),
        news_repo=FakeNewsRepository(),
        rss_client=FakeRssClient([]),
    )
    result = service.run()
    assert result.inserted == 0
