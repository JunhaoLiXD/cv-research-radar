"""RSS and Atom feed collection with per-feed failure isolation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from time import struct_time
from typing import Any

import feedparser

from cv_radar.config import FeedConfig
from cv_radar.http import ResilientHttpClient
from cv_radar.models import ResearchItem
from cv_radar.sources.base import FetchResult


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())


def _published(entry: Any) -> datetime:
    parsed: struct_time | None = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=UTC)
    text = entry.get("published") or entry.get("updated")
    if text:
        try:
            value = parsedate_to_datetime(text)
            return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
            except ValueError:
                pass
    return datetime.now(UTC)


def parse_feed(content: bytes | str, config: FeedConfig) -> list[ResearchItem]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"invalid feed: {parsed.bozo_exception}")
    items: list[ResearchItem] = []
    for entry in parsed.entries:
        title = _plain_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        published_at = _published(entry)
        stable = entry.get("id") or entry.get("guid") or link
        digest = hashlib.sha256(str(stable).encode("utf-8")).hexdigest()[:24]
        authors = [author.get("name", "") for author in entry.get("authors", []) if author.get("name")]
        if not authors and entry.get("author"):
            authors = [entry.author]
        tags = [tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")]
        items.append(
            ResearchItem(
                source=config.name,
                source_id=f"feed:{digest}",
                item_type=config.item_type,
                title=title,
                abstract=_plain_text(entry.get("summary") or entry.get("description") or ""),
                authors=authors,
                published_at=published_at,
                url=link,
                categories=tags,
                raw_metadata={"feed_url": config.url, "entry_id": stable},
            )
        )
    return items


class RSSSource:
    def __init__(self, feeds: list[FeedConfig], http: ResilientHttpClient) -> None:
        self.feeds = feeds
        self.http = http

    def fetch(self) -> FetchResult:
        result = FetchResult()
        for feed in self.feeds:
            if not feed.enabled:
                continue
            try:
                response = self.http.get(feed.url)
                result.items.extend(parse_feed(response.content, feed))
            except Exception as exc:  # feed boundary: one broken feed cannot stop the rest
                result.errors.append(f"Feed {feed.name}: {type(exc).__name__}: {exc}")
        return result
