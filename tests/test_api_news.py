from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.auth import verify_api_key
from app.api.dependencies import get_asset_repo, get_news_repo
from app.api.main import app
from app.database.models import Asset
from app.news.schemas import NewsArticle


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[verify_api_key] = lambda: None
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _asset(asset_id, symbol):
    return Asset(id=asset_id, symbol=symbol, name=symbol, coingecko_id=symbol.lower(), active=True, in_asset=True, created_at=datetime.now(UTC))


def _article(article_id, symbols, minutes_ago=0, title="Headline"):
    return NewsArticle(
        id=article_id, published_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        source="example-feed", title=title, url=f"https://example.com/{article_id}",
        summary=None, sentiment=None, relevant_assets=symbols,
    )


class FakeAssetRepo:
    def __init__(self, assets):
        self._assets = assets

    def get_active_assets(self):
        return self._assets


class FakeNewsRepo:
    """Mirrors the real `NewsRepository.get_recent_relevant_news` contract:
    keyed by symbol, each list capped at `limit_per_asset`, filtered to
    `[since, until]` -- so the endpoint's merge/dedupe/sort logic is
    exercised the same way it would be against the real repository."""

    def __init__(self, by_symbol):
        self._by_symbol = by_symbol

    def get_recent_relevant_news(self, symbols, since, until, limit_per_asset):
        if not symbols:
            return {}
        result = {}
        for symbol in symbols:
            articles = [a for a in self._by_symbol.get(symbol, []) if since <= a.published_at <= until]
            result[symbol] = articles[:limit_per_asset]
        return result


def _override(assets, by_symbol):
    app.dependency_overrides[get_asset_repo] = lambda: FakeAssetRepo(assets)
    app.dependency_overrides[get_news_repo] = lambda: FakeNewsRepo(by_symbol)


def test_no_active_assets_returns_empty_never_an_error(client):
    _override(assets=[], by_symbol={})
    response = client.get("/news/recent")
    assert response.status_code == 200
    assert response.json() == []


def test_returns_articles_sorted_newest_first(client):
    older = _article("n1", ["SOL"], minutes_ago=120, title="Older")
    newer = _article("n2", ["SOL"], minutes_ago=5, title="Newer")
    _override(assets=[_asset("a1", "SOL")], by_symbol={"SOL": [older, newer]})
    response = client.get("/news/recent")
    assert response.status_code == 200
    titles = [a["title"] for a in response.json()]
    assert titles == ["Newer", "Older"]


def test_an_article_relevant_to_multiple_assets_is_deduplicated(client):
    shared = _article("n1", ["SOL", "BTC"], minutes_ago=10)
    _override(
        assets=[_asset("a1", "SOL"), _asset("a2", "BTC")],
        by_symbol={"SOL": [shared], "BTC": [shared]},
    )
    response = client.get("/news/recent")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_limit_truncates_the_merged_result(client):
    articles = [_article(f"n{i}", ["SOL"], minutes_ago=i) for i in range(5)]
    _override(assets=[_asset("a1", "SOL")], by_symbol={"SOL": articles})
    response = client.get("/news/recent?limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_no_limit_by_default_returns_every_matching_article(client):
    articles = [_article(f"n{i}", ["SOL"], minutes_ago=i) for i in range(25)]
    _override(assets=[_asset("a1", "SOL")], by_symbol={"SOL": articles})
    response = client.get("/news/recent")
    assert response.status_code == 200
    assert len(response.json()) == 25


def test_relevant_assets_field_carries_real_symbols_not_asset_ids(client):
    article = _article("n1", ["SOL", "BTC"], minutes_ago=1)
    _override(
        assets=[_asset("a1", "SOL"), _asset("a2", "BTC")],
        by_symbol={"SOL": [article], "BTC": [article]},
    )
    response = client.get("/news/recent")
    assert response.json()[0]["relevant_assets"] == ["SOL", "BTC"]
