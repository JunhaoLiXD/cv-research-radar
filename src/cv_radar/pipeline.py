"""End-to-end orchestration with source and model failure isolation."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from cv_radar.analysis import KeywordAnalyzer, LLMAnalyzer
from cv_radar.config import FeedConfig, ProjectConfig, load_project_config
from cv_radar.http import ResilientHttpClient
from cv_radar.models import ItemType, RankedItem, ResearchItem, RunRecord
from cv_radar.pdf_reporting import write_pdf_report
from cv_radar.processing import Deduplicator, RuleFilter
from cv_radar.ranking import rank_items, select_daily_items
from cv_radar.reporting import render_markdown_report, write_report
from cv_radar.sources import ArxivSource, RSSSource, SemanticScholarClient, parse_arxiv_atom, parse_feed
from cv_radar.state import StateStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineResult:
    target_date: date
    report_path: Path
    markdown_path: Path
    items: list[RankedItem]
    fetched_count: int
    candidate_count: int
    source_errors: list[str]


class RadarPipeline:
    def __init__(
        self,
        *,
        project_root: str | Path = ".",
        config_dir: str | Path = "config",
        config: ProjectConfig | None = None,
        http: ResilientHttpClient | None = None,
        llm: LLMAnalyzer | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        config_path = Path(config_dir)
        if not config_path.is_absolute():
            config_path = self.project_root / config_path
        self.config = config or load_project_config(config_path)
        self._owns_http = http is None
        self.http = http or ResilientHttpClient()
        self.llm = llm or LLMAnalyzer.from_environment()
        self.state = StateStore(self.project_root / "state")

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    def _fetch_fixtures(self, fixture_dir: Path, target_date: date) -> tuple[list[ResearchItem], list[str]]:
        items: list[ResearchItem] = []
        errors: list[str] = []
        fixture_specs = [
            ("arXiv fixture", "arxiv_atom.xml", lambda data: parse_arxiv_atom(data)),
            (
                "RSS fixture",
                "rss.xml",
                lambda data: parse_feed(data, FeedConfig(name="Vision Lab Fixture", url="fixture://rss")),
            ),
            (
                "Atom fixture",
                "atom.xml",
                lambda data: parse_feed(data, FeedConfig(name="Imaging Lab Fixture", url="fixture://atom")),
            ),
        ]
        for name, filename, parser in fixture_specs:
            path = fixture_dir / filename
            if not path.exists():
                continue
            try:
                items.extend(parser(path.read_bytes()))
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
        items = [item for item in items if item.published_at.date() == target_date]
        semantic_path = fixture_dir / "semantic_scholar.json"
        if semantic_path.exists():
            try:
                data = json.loads(semantic_path.read_text(encoding="utf-8"))
                for index, item in enumerate(items):
                    if item.item_type == ItemType.PAPER and item.title.casefold() == str(data.get("title", "")).casefold():
                        from cv_radar.sources.semantic_scholar import parse_semantic_scholar_response

                        items[index] = parse_semantic_scholar_response(data, item)
            except Exception as exc:
                errors.append(f"Semantic Scholar fixture: {type(exc).__name__}: {exc}")
        return items, errors

    def _fetch_live(self, target_date: date) -> tuple[list[ResearchItem], list[str]]:
        items: list[ResearchItem] = []
        errors: list[str] = []
        arxiv = ArxivSource(self.config.sources.arxiv, self.http).fetch(target_date)
        items.extend(arxiv.items)
        errors.extend(arxiv.errors)
        feeds = RSSSource(self.config.sources.feeds, self.http).fetch()
        items.extend(item for item in feeds.items if item.published_at.date() == target_date)
        errors.extend(feeds.errors)
        if self.config.sources.semantic_scholar.enabled:
            scholar = SemanticScholarClient(self.http, os.getenv("SEMANTIC_SCHOLAR_API_KEY"))
            items = [scholar.enrich(item) if item.item_type == ItemType.PAPER else item for item in items]
        return items, errors

    def run(self, target_date: date, *, fixture_dir: str | Path | None = None) -> PipelineResult:
        started = datetime.now(UTC)
        if fixture_dir:
            fetched, source_errors = self._fetch_fixtures(Path(fixture_dir), target_date)
        else:
            fetched, source_errors = self._fetch_live(target_date)
        deduplicated = Deduplicator(self.config.ranking.fuzzy_title_threshold).deduplicate(fetched)
        matches = RuleFilter(
            self.config.interests, self.config.ranking.minimum_rule_score
        ).filter(deduplicated)
        keyword = KeywordAnalyzer(self.config.interests)
        analyzed = []
        for match in matches:
            fallback = keyword.analyze(match)
            analysis, used_llm = self.llm.analyze(match, fallback)
            analyzed.append((match.item, analysis, used_llm))
        ranked = rank_items(analyzed, self.config.ranking, self.config.interests)
        selected = select_daily_items(
            ranked,
            self.config.interests.daily_max_recommendations,
            self.config.ranking.topic_daily_cap,
        )
        content = render_markdown_report(
            target_date,
            selected,
            fetched_count=len(fetched),
            candidate_count=len(matches),
            llm_enabled=self.llm.enabled,
            source_errors=source_errors,
        )
        markdown_path = write_report(self.project_root / "reports", target_date, content)
        report_path = write_pdf_report(
            self.project_root / "reports",
            target_date,
            selected,
            fetched_count=len(fetched),
            candidate_count=len(matches),
            llm_enabled=self.llm.enabled,
            source_errors=source_errors,
        )
        self.state.upsert_seen(deduplicated)
        finished = datetime.now(UTC)
        self.state.upsert_run(
            RunRecord(
                run_key=f"daily:{target_date.isoformat()}",
                target_date=target_date.isoformat(),
                started_at=started,
                finished_at=finished,
                fetched_count=len(fetched),
                candidate_count=len(matches),
                report_count=len(selected),
                source_errors=source_errors,
                llm_enabled=self.llm.enabled,
                report_path=str(report_path.relative_to(self.project_root)),
            )
        )
        return PipelineResult(
            target_date=target_date,
            report_path=report_path,
            markdown_path=markdown_path,
            items=selected,
            fetched_count=len(fetched),
            candidate_count=len(matches),
            source_errors=source_errors,
        )
