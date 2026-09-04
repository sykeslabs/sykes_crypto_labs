import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger("crypto_ai_portfolio.news")

# Free, no-key-required RSS feeds. Deliberately not user-configurable via env
# yet — keep it simple until there's a reason to swap sources.
NEWS_FEEDS: dict[str, str] = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "CoinTelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
}


@dataclass
class RawFeedEntry:
    source: str
    title: str
    url: str
    summary: str | None
    published_at_raw: str | None


class RssClient:
    """Fetches and parses RSS 2.0 feeds. Tolerant of malformed individual
    entries or unreachable feeds — one bad feed must not take down the run.
    """

    def __init__(self, feeds: dict[str, str] | None = None, timeout: float = 15.0) -> None:
        self._feeds = feeds or NEWS_FEEDS
        self._timeout = timeout

    def fetch_all(self) -> list[RawFeedEntry]:
        entries: list[RawFeedEntry] = []
        with httpx.Client(
            timeout=self._timeout, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            for source, url in self._feeds.items():
                try:
                    entries.extend(self._fetch_feed(client, source, url))
                except Exception as exc:
                    logger.warning("Failed to fetch feed '%s' (%s): %s", source, url, exc)
        return entries

    def _fetch_feed(self, client: httpx.Client, source: str, url: str) -> list[RawFeedEntry]:
        response = client.get(url)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        entries = []
        for item in root.findall("./channel/item"):
            title = _text(item, "title")
            link = _text(item, "link")
            if not title or not link:
                continue
            entries.append(
                RawFeedEntry(
                    source=source,
                    title=title.strip(),
                    url=link.strip(),
                    summary=_text(item, "description"),
                    published_at_raw=_text(item, "pubDate"),
                )
            )
        return entries


def _text(item: ET.Element, tag: str) -> str | None:
    el = item.find(tag)
    return el.text if el is not None else None


def parse_pub_date(raw: str | None):
    """Parses an RFC 822 pubDate string into a UTC datetime. Returns None if
    absent or unparseable (caller decides how to handle a missing date)."""
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
