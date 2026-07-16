"""Layered deduplication with a reserved embedding extension point."""

from __future__ import annotations

import re
import unicodedata
from typing import Protocol

from rapidfuzz import fuzz

from cv_radar.models import ItemType, ResearchItem


class EmbeddingDuplicateDetector(Protocol):
    """Future semantic-deduplication adapter; no embedding API is called in v1."""

    def is_duplicate(self, candidate: ResearchItem, existing: ResearchItem) -> bool: ...


def normalize_title(title: str) -> str:
    value = unicodedata.normalize("NFKC", title).casefold()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _normalize_identifier(kind: str, value: object) -> str:
    text = str(value).strip().casefold()
    if kind.casefold() == "doi":
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    if kind.casefold() == "arxiv":
        text = re.sub(r"v\d+$", "", text)
    return text


def stable_identifier_keys(item: ResearchItem) -> set[str]:
    keys = {f"source:{item.source_id.casefold()}"}
    external_ids = item.raw_metadata.get("external_ids") or {}
    if isinstance(external_ids, dict):
        for kind, value in external_ids.items():
            if value:
                keys.add(f"{str(kind).casefold()}:{_normalize_identifier(str(kind), value)}")
    return keys


def item_fingerprint(item: ResearchItem) -> str:
    stable = sorted(stable_identifier_keys(item))
    preferred = next((key for key in stable if not key.startswith("source:")), None)
    return preferred or f"title:{normalize_title(item.title)}"


def _unique(left: list[str], right: list[str]) -> list[str]:
    return list(dict.fromkeys([*left, *right]))


def merge_items(left: ResearchItem, right: ResearchItem) -> ResearchItem:
    primary, secondary = left, right
    if left.item_type != ItemType.PAPER and right.item_type == ItemType.PAPER:
        primary, secondary = right, left
    raw = {**secondary.raw_metadata, **primary.raw_metadata}
    ext = {
        **(secondary.raw_metadata.get("external_ids") or {}),
        **(primary.raw_metadata.get("external_ids") or {}),
    }
    if ext:
        raw["external_ids"] = ext
    return primary.model_copy(
        update={
            "abstract": max((primary.abstract, secondary.abstract), key=len),
            "authors": _unique(primary.authors, secondary.authors),
            "categories": _unique(primary.categories, secondary.categories),
            "pdf_url": primary.pdf_url or secondary.pdf_url,
            "code_url": primary.code_url or secondary.code_url,
            "venue": primary.venue or secondary.venue,
            "citation_count": max(
                (value for value in (primary.citation_count, secondary.citation_count) if value is not None),
                default=None,
            ),
            "raw_metadata": raw,
        }
    )


class Deduplicator:
    def __init__(
        self,
        fuzzy_threshold: float = 94.0,
        embedding_detector: EmbeddingDuplicateDetector | None = None,
    ) -> None:
        self.fuzzy_threshold = fuzzy_threshold
        self.embedding_detector = embedding_detector

    def deduplicate(self, items: list[ResearchItem]) -> list[ResearchItem]:
        kept: list[ResearchItem] = []
        identifier_index: dict[str, int] = {}
        title_index: dict[str, int] = {}
        for candidate in items:
            duplicate_index: int | None = None
            for key in stable_identifier_keys(candidate):
                if key in identifier_index:
                    duplicate_index = identifier_index[key]
                    break
            normalized = normalize_title(candidate.title)
            if duplicate_index is None:
                duplicate_index = title_index.get(normalized)
            if duplicate_index is None:
                for index, existing in enumerate(kept):
                    score = fuzz.ratio(normalized, normalize_title(existing.title))
                    if score >= self.fuzzy_threshold:
                        duplicate_index = index
                        break
                    if self.embedding_detector and self.embedding_detector.is_duplicate(candidate, existing):
                        duplicate_index = index
                        break
            if duplicate_index is None:
                duplicate_index = len(kept)
                kept.append(candidate)
            else:
                kept[duplicate_index] = merge_items(kept[duplicate_index], candidate)
            title_index[normalize_title(kept[duplicate_index].title)] = duplicate_index
            for key in stable_identifier_keys(kept[duplicate_index]):
                identifier_index[key] = duplicate_index
        return kept
