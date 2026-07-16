"""arXiv Atom API collection and normalization."""

from __future__ import annotations

import re
from datetime import date, datetime
from xml.etree import ElementTree as ET

from cv_radar.config import ArxivConfig
from cv_radar.http import ResilientHttpClient
from cv_radar.models import ItemType, ResearchItem
from cv_radar.sources.base import FetchResult

ATOM = "http://www.w3.org/2005/Atom"
ARXIV = "http://arxiv.org/schemas/atom"
ARXIV_API_URL = "https://export.arxiv.org/api/query"


def _text(element: ET.Element | None, default: str = "") -> str:
    if element is None or element.text is None:
        return default
    return " ".join(element.text.split())


def _arxiv_id(value: str) -> str:
    identifier = value.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", identifier)


def parse_arxiv_atom(content: bytes | str) -> list[ResearchItem]:
    root = ET.fromstring(content)
    items: list[ResearchItem] = []
    for entry in root.findall(f"{{{ATOM}}}entry"):
        raw_id = _text(entry.find(f"{{{ATOM}}}id"))
        identifier = _arxiv_id(raw_id)
        title = _text(entry.find(f"{{{ATOM}}}title"))
        abstract = _text(entry.find(f"{{{ATOM}}}summary"))
        published = datetime.fromisoformat(_text(entry.find(f"{{{ATOM}}}published")).replace("Z", "+00:00"))
        authors = [
            _text(author.find(f"{{{ATOM}}}name"))
            for author in entry.findall(f"{{{ATOM}}}author")
            if _text(author.find(f"{{{ATOM}}}name"))
        ]
        categories = [node.attrib["term"] for node in entry.findall(f"{{{ATOM}}}category") if node.attrib.get("term")]
        page_url = raw_id
        pdf_url: str | None = None
        for link in entry.findall(f"{{{ATOM}}}link"):
            href = link.attrib.get("href")
            if not href:
                continue
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = href
            elif link.attrib.get("rel") == "alternate":
                page_url = href
        doi = _text(entry.find(f"{{{ARXIV}}}doi")) or None
        external_ids: dict[str, str] = {"ArXiv": identifier}
        if doi:
            external_ids["DOI"] = doi
        items.append(
            ResearchItem(
                source="arXiv",
                source_id=f"arxiv:{identifier}",
                item_type=ItemType.PAPER,
                title=title,
                abstract=abstract,
                authors=authors,
                published_at=published,
                url=page_url,
                pdf_url=pdf_url,
                categories=categories,
                venue=_text(entry.find(f"{{{ARXIV}}}journal_ref")) or None,
                raw_metadata={
                    "external_ids": external_ids,
                    "updated": _text(entry.find(f"{{{ATOM}}}updated")),
                    "comment": _text(entry.find(f"{{{ARXIV}}}comment")),
                },
            )
        )
    return items


class ArxivSource:
    def __init__(self, config: ArxivConfig, http: ResilientHttpClient) -> None:
        self.config = config
        self.http = http

    def _query(self, target_date: date) -> str:
        categories = " OR ".join(f"cat:{category}" for category in self.config.categories)
        query = f"({categories})" if len(self.config.categories) > 1 else categories
        if self.config.search_keywords:
            keywords = " OR ".join(f'all:"{keyword}"' for keyword in self.config.search_keywords)
            query = f"{query} AND ({keywords})"
        stamp = target_date.strftime("%Y%m%d")
        return f"{query} AND submittedDate:[{stamp}0000 TO {stamp}2359]"

    def fetch(self, target_date: date) -> FetchResult:
        if not self.config.enabled:
            return FetchResult()
        try:
            response = self.http.get(
                ARXIV_API_URL,
                params={
                    "search_query": self._query(target_date),
                    "start": 0,
                    "max_results": self.config.max_results,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
            )
            return FetchResult(items=parse_arxiv_atom(response.content))
        except Exception as exc:  # source boundary: downstream sources must continue
            return FetchResult(errors=[f"arXiv: {type(exc).__name__}: {exc}"])
