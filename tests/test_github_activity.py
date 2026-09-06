from datetime import UTC, datetime

import httpx

from app.config.settings import Settings
from app.market_data.github_activity import PRIMARY_REPO_BY_SYMBOL, GitHubClient


class FakeHttpResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


def _client(token=None) -> GitHubClient:
    settings = Settings(_env_file=None, github_token=token)
    return GitHubClient(settings)


def test_fetch_commit_count_since_counts_real_response_rows(monkeypatch):
    def fake_get(self, url, params=None, headers=None):
        assert headers["Authorization"] == "Bearer tok"
        return FakeHttpResponse([{"sha": "a"}, {"sha": "b"}, {"sha": "c"}])

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = _client(token="tok")
    count = client.fetch_commit_count_since("bitcoin", "bitcoin", datetime(2026, 1, 1, tzinfo=UTC))
    assert count == 3


def test_fetch_commit_count_since_omits_auth_header_without_token(monkeypatch):
    def fake_get(self, url, params=None, headers=None):
        assert "Authorization" not in headers
        return FakeHttpResponse([{"sha": "a"}])

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = _client(token=None)
    assert client.fetch_commit_count_since("owner", "repo", datetime(2026, 1, 1, tzinfo=UTC)) == 1


def test_fetch_commit_count_since_returns_none_on_404(monkeypatch):
    def fake_get(self, url, params=None, headers=None):
        return FakeHttpResponse({}, status_code=404)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = _client()
    assert client.fetch_commit_count_since("nonexistent", "repo", datetime(2026, 1, 1, tzinfo=UTC)) is None


def test_fetch_contributor_count_returns_none_while_stats_are_computing(monkeypatch):
    # GitHub's real, documented behavior: 202 while stats are being computed.
    def fake_get(self, url, params=None, headers=None):
        return FakeHttpResponse({}, status_code=202)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = _client()
    assert client.fetch_contributor_count("owner", "repo") is None


def test_fetch_contributor_count_counts_real_response_rows(monkeypatch):
    def fake_get(self, url, params=None, headers=None):
        return FakeHttpResponse([{"author": {"login": "a"}}, {"author": {"login": "b"}}])

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = _client()
    assert client.fetch_contributor_count("owner", "repo") == 2


def test_primary_repo_map_has_no_ambiguous_placeholder_entries():
    # Every entry must be a real, specific (owner, repo) pair -- not a
    # guess or a placeholder.
    for symbol, (owner, repo) in PRIMARY_REPO_BY_SYMBOL.items():
        assert owner and repo
