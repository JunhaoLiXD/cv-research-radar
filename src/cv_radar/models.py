"""Typed domain models shared by the collection and reporting pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ItemType(str, Enum):
    PAPER = "paper"
    BLOG = "blog"
    REPOSITORY = "repository"
    DATASET = "dataset"
    TOOL = "tool"


class RecommendedAction(str, Enum):
    READ_DEEPLY = "精读"
    BROWSE = "浏览"
    WATCH = "观察"
    SKIP = "跳过"


class ResearchItem(BaseModel):
    """Normalized representation of every source item."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_id: str
    item_type: ItemType
    title: str
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    published_at: datetime
    url: str
    pdf_url: str | None = None
    code_url: str | None = None
    categories: list[str] = Field(default_factory=list)
    venue: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("published_at")
    @classmethod
    def ensure_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("title", "source", "source_id", "url")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class LLMAnalysis(BaseModel):
    """Strict Structured Outputs schema and keyword-fallback analysis model."""

    model_config = ConfigDict(extra="forbid")

    topics: list[str]
    relevance_score: float = Field(ge=0, le=100)
    novelty_score: float = Field(ge=0, le=100)
    evidence_score: float = Field(ge=0, le=100)
    reproducibility_score: float = Field(ge=0, le=100)
    summary_zh: str
    highlights_zh: list[str] = Field(min_length=1, max_length=5)
    novelty_zh: str
    core_idea: str
    why_it_matters: str
    limitations: str
    project_connections: str
    recommended_action: RecommendedAction


class RankedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: ResearchItem
    analysis: LLMAnalysis
    trend_score: float = Field(ge=0, le=100)
    exploration_score: float = Field(ge=0, le=100)
    final_score: float = Field(ge=0, le=100)
    llm_analyzed: bool = False


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_key: str
    target_date: str
    started_at: datetime
    finished_at: datetime
    fetched_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    report_count: int = Field(ge=0)
    source_errors: list[str] = Field(default_factory=list)
    llm_enabled: bool
    report_path: str
