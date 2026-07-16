import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from cv_radar.config import FeedConfig
from cv_radar.http import ResilientHttpClient
from cv_radar.models import ItemType, ResearchItem
from cv_radar.sources.arxiv import parse_arxiv_atom
from cv_radar.sources.rss import RSSSource, parse_feed
from cv_radar.sources.semantic_scholar import SemanticScholarClient, parse_semantic_scholar_response


FIXTURES = Path(__file__).parent / "fixtures"


def _item() -> ResearchItem:
    return ResearchItem(
        source="arXiv",
        source_id="arxiv:2607.01234",
        item_type=ItemType.PAPER,
        title="Foundation Models for Microscopy Cell Tracking",
        abstract="cell tracking",
        authors=["Ada Vision"],
        published_at=datetime(2026, 7, 10, tzinfo=UTC),
        url="https://arxiv.org/abs/2607.01234",
        raw_metadata={"external_ids": {"ArXiv": "2607.01234"}},
    )


def test_parse_arxiv_atom() -> None:
    items = parse_arxiv_atom((FIXTURES / "arxiv_atom.xml").read_bytes())

    assert len(items) == 2
    assert items[0].source_id == "arxiv:2607.01234"
    assert items[0].authors == ["Ada Vision", "Lin Bio"]
    assert items[0].categories == ["cs.CV", "eess.IV"]
    assert items[0].pdf_url == "https://arxiv.org/pdf/2607.01234"
    assert items[0].raw_metadata["external_ids"]["DOI"] == "10.1000/example.1234"


def test_parse_rss_and_atom() -> None:
    config = FeedConfig(name="Fixture Feed", url="https://example.org/feed")
    rss_items = parse_feed((FIXTURES / "rss.xml").read_bytes(), config)
    atom_items = parse_feed((FIXTURES / "atom.xml").read_bytes(), config)

    assert rss_items[0].title == "Building World Models for Video Understanding"
    assert "engineering deep dive" in rss_items[0].abstract
    assert rss_items[0].published_at == datetime(2026, 7, 10, 8, tzinfo=UTC)
    assert atom_items[0].authors == ["Imaging Lab"]


def test_parse_semantic_scholar_response() -> None:
    data = json.loads((FIXTURES / "semantic_scholar.json").read_text(encoding="utf-8"))
    enriched = parse_semantic_scholar_response(data, _item())

    assert enriched.citation_count == 17
    assert enriched.venue == "MICCAI"
    assert enriched.pdf_url == "https://example.org/paper.pdf"
    assert enriched.raw_metadata["external_ids"]["DOI"] == "10.1000/example.1234"


def test_semantic_scholar_failure_returns_original() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="temporarily unavailable")

    http = ResilientHttpClient(
        transport=httpx.MockTransport(handler), max_retries=1, min_interval_seconds=0, sleeper=lambda _: None
    )
    original = _item()

    assert SemanticScholarClient(http).enrich(original) == original


def test_invalid_feed_does_not_stop_other_feeds() -> None:
    rss = (FIXTURES / "rss.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if "bad" in str(request.url):
            return httpx.Response(500, text="bad feed")
        return httpx.Response(200, content=rss)

    http = ResilientHttpClient(
        transport=httpx.MockTransport(handler), max_retries=0, min_interval_seconds=0, sleeper=lambda _: None
    )
    feeds = [
        FeedConfig(name="Bad", url="https://bad.example/feed"),
        FeedConfig(name="Good", url="https://good.example/feed"),
    ]
    result = RSSSource(feeds, http).fetch()

    assert len(result.items) == 1
    assert len(result.errors) == 1
    assert result.items[0].source == "Good"
