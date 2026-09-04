import hashlib
from datetime import datetime

from pydantic import BaseModel


class NewsArticle(BaseModel):
    """A normalized news article, matched against the asset universe.

    `id` is None until persisted. `content_hash` is the dedup key.
    """

    id: str | None = None
    published_at: datetime
    source: str
    title: str
    url: str
    summary: str | None = None
    sentiment: str | None = None
    relevant_assets: list[str] = []

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.title}|{self.url}".encode("utf-8")).hexdigest()

    def to_row(self) -> dict:
        return {
            "published_at": self.published_at.isoformat(),
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "sentiment": self.sentiment,
            "relevant_assets": self.relevant_assets,
            "content_hash": self.content_hash,
        }
