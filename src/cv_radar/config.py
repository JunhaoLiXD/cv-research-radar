"""YAML configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from cv_radar.models import ItemType


class InterestsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high_priority: list[str]
    medium_priority: list[str]
    exploration: list[str]
    exclude_keywords: list[str] = Field(default_factory=list)
    followed_authors: list[str] = Field(default_factory=list)
    followed_venues: list[str] = Field(default_factory=list)
    daily_max_recommendations: int = Field(default=15, ge=1, le=100)


class ArxivConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    categories: list[str] = Field(default_factory=lambda: ["cs.CV", "eess.IV"])
    search_keywords: list[str] = Field(default_factory=list)
    max_results: int = Field(default=100, ge=1, le=2000)


class SemanticScholarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class FeedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    item_type: ItemType = ItemType.BLOG
    enabled: bool = True


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arxiv: ArxivConfig = Field(default_factory=ArxivConfig)
    semantic_scholar: SemanticScholarConfig = Field(default_factory=SemanticScholarConfig)
    feeds: list[FeedConfig] = Field(default_factory=list)


class RankingWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: float = Field(default=0.35, ge=0, le=1)
    novelty: float = Field(default=0.25, ge=0, le=1)
    evidence: float = Field(default=0.15, ge=0, le=1)
    reproducibility: float = Field(default=0.15, ge=0, le=1)
    trend: float = Field(default=0.05, ge=0, le=1)
    exploration: float = Field(default=0.05, ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "RankingWeights":
        total = sum(
            (
                self.relevance,
                self.novelty,
                self.evidence,
                self.reproducibility,
                self.trend,
                self.exploration,
            )
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ranking weights must sum to 1.0, got {total}")
        return self


class RankingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: RankingWeights = Field(default_factory=RankingWeights)
    fuzzy_title_threshold: float = Field(default=94.0, ge=0, le=100)
    minimum_rule_score: float = Field(default=15.0, ge=0, le=100)
    topic_daily_cap: float = Field(default=0.4, gt=0, le=1)


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interests: InterestsConfig
    sources: SourcesConfig
    ranking: RankingConfig


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    return data


def load_project_config(config_dir: str | Path = "config") -> ProjectConfig:
    base = Path(config_dir)
    return ProjectConfig(
        interests=InterestsConfig.model_validate(_read_yaml(base / "interests.yaml")),
        sources=SourcesConfig.model_validate(_read_yaml(base / "sources.yaml")),
        ranking=RankingConfig.model_validate(_read_yaml(base / "ranking.yaml")),
    )
