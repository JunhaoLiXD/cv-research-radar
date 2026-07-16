"""Semantic Scholar Graph API enrichment."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from cv_radar.http import ResilientHttpClient
from cv_radar.models import ResearchItem

logger = logging.getLogger(__name__)

API_ROOT = "https://api.semanticscholar.org/graph/v1"
FIELDS = ",".join(
    [
        "paperId",
        "title",
        "authors",
        "citationCount",
        "venue",
        "publicationDate",
        "externalIds",
        "openAccessPdf",
        "url",
    ]
)


def parse_semantic_scholar_response(data: dict[str, Any], item: ResearchItem) -> ResearchItem:
    if not data or data.get("error"):
        return item
    external_ids = dict(item.raw_metadata.get("external_ids") or {})
    external_ids.update({str(k): str(v) for k, v in (data.get("externalIds") or {}).items() if v})
    raw = dict(item.raw_metadata)
    raw["external_ids"] = external_ids
    raw["semantic_scholar"] = data
    pdf = (data.get("openAccessPdf") or {}).get("url") or item.pdf_url
    authors = item.authors or [author.get("name", "") for author in data.get("authors", []) if author.get("name")]
    published_at = item.published_at
    if not published_at and data.get("publicationDate"):
        published_at = datetime.fromisoformat(data["publicationDate"]).replace(tzinfo=UTC)
    return item.model_copy(
        update={
            "authors": authors,
            "published_at": published_at,
            "pdf_url": pdf,
            "venue": data.get("venue") or item.venue,
            "citation_count": data.get("citationCount") if data.get("citationCount") is not None else item.citation_count,
            "raw_metadata": raw,
        }
    )


class SemanticScholarClient:
    def __init__(self, http: ResilientHttpClient, api_key: str | None = None) -> None:
        self.http = http
        self._headers = {"x-api-key": api_key} if api_key else {}

    def _lookup(self, item: ResearchItem) -> dict[str, Any]:
        external_ids = item.raw_metadata.get("external_ids") or {}
        arxiv_id = external_ids.get("ArXiv")
        doi = external_ids.get("DOI")
        if arxiv_id:
            locator = f"ARXIV:{arxiv_id}"
            return self.http.get_json(
                f"{API_ROOT}/paper/{quote(locator, safe=':')}", params={"fields": FIELDS}, headers=self._headers
            )
        if doi:
            locator = f"DOI:{doi}"
            return self.http.get_json(
                f"{API_ROOT}/paper/{quote(locator, safe=':')}", params={"fields": FIELDS}, headers=self._headers
            )
        result = self.http.get_json(
            f"{API_ROOT}/paper/search",
            params={"query": item.title, "limit": 1, "fields": FIELDS},
            headers=self._headers,
        )
        matches = result.get("data", []) if isinstance(result, dict) else []
        return matches[0] if matches else {}

    def enrich(self, item: ResearchItem) -> ResearchItem:
        try:
            return parse_semantic_scholar_response(self._lookup(item), item)
        except Exception as exc:  # enrichment is optional; preserve the original record
            logger.error("Semantic Scholar enrichment failed for %s: %s", item.source_id, exc)
            return item
