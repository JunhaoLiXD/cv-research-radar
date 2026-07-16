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
from cv_radar.manual_review import (
    load_review_bundle,
    load_review_submission,
    review_paths,
    validate_submission,
    write_review_bundle,
)
from cv_radar.models import ItemType, RankedItem, ResearchItem, ReviewBundle, ReviewCandidate, RunRecord
from cv_radar.pdf_reporting import write_pdf_report
from cv_radar.processing import Deduplicator, RuleFilter
from cv_radar.processing.dedupe import item_fingerprint
from cv_radar.processing.filtering import RuleMatch
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


@dataclass(slots=True)
class ReviewPreparationResult:
    target_date: date
    bundle_path: Path
    prompt_path: Path
    analysis_path: Path
    fetched_count: int
    rule_candidate_count: int
    review_candidate_count: int
    source_errors: list[str]


@dataclass(slots=True)
class _CollectionResult:
    fetched: list[ResearchItem]
    deduplicated: list[ResearchItem]
    matches: list[RuleMatch]
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

    def _collect(self, target_date: date, fixture_dir: str | Path | None) -> _CollectionResult:
        if fixture_dir:
            fetched, source_errors = self._fetch_fixtures(Path(fixture_dir), target_date)
        else:
            fetched, source_errors = self._fetch_live(target_date)
        deduplicated = Deduplicator(self.config.ranking.fuzzy_title_threshold).deduplicate(fetched)
        matches = RuleFilter(
            self.config.interests, self.config.ranking.minimum_rule_score
        ).filter(deduplicated)
        return _CollectionResult(
            fetched=fetched,
            deduplicated=deduplicated,
            matches=matches,
            source_errors=source_errors,
        )

    def _persist_result(
        self,
        target_date: date,
        selected: list[RankedItem],
        *,
        started: datetime,
        fetched_count: int,
        candidate_count: int,
        llm_enabled: bool,
        source_errors: list[str],
        seen_items: list[ResearchItem],
    ) -> PipelineResult:
        content = render_markdown_report(
            target_date,
            selected,
            fetched_count=fetched_count,
            candidate_count=candidate_count,
            llm_enabled=llm_enabled,
            source_errors=source_errors,
        )
        markdown_path = write_report(self.project_root / "reports", target_date, content)
        report_path = write_pdf_report(
            self.project_root / "reports",
            target_date,
            selected,
            fetched_count=fetched_count,
            candidate_count=candidate_count,
            llm_enabled=llm_enabled,
            source_errors=source_errors,
        )
        self.state.upsert_seen(seen_items)
        finished = datetime.now(UTC)
        self.state.upsert_run(
            RunRecord(
                run_key=f"daily:{target_date.isoformat()}",
                target_date=target_date.isoformat(),
                started_at=started,
                finished_at=finished,
                fetched_count=fetched_count,
                candidate_count=candidate_count,
                report_count=len(selected),
                source_errors=source_errors,
                llm_enabled=llm_enabled,
                report_path=str(report_path.relative_to(self.project_root)),
            )
        )
        return PipelineResult(
            target_date=target_date,
            report_path=report_path,
            markdown_path=markdown_path,
            items=selected,
            fetched_count=fetched_count,
            candidate_count=candidate_count,
            source_errors=source_errors,
        )

    def prepare_review(
        self,
        target_date: date,
        *,
        fixture_dir: str | Path | None = None,
    ) -> ReviewPreparationResult:
        """Collect and export a bounded candidate set without calling an LLM API."""
        collection = self._collect(target_date, fixture_dir)
        keyword = KeywordAnalyzer(self.config.interests)
        fallback_by_fingerprint = {
            item_fingerprint(match.item): keyword.analyze(match) for match in collection.matches
        }
        fallback_ranked = rank_items(
            [
                (match.item, fallback_by_fingerprint[item_fingerprint(match.item)], False)
                for match in collection.matches
            ],
            self.config.ranking,
            self.config.interests,
        )
        review_items = select_daily_items(
            fallback_ranked,
            self.config.interests.daily_max_recommendations,
            self.config.ranking.topic_daily_cap,
        )
        match_by_fingerprint = {
            item_fingerprint(match.item): match for match in collection.matches
        }
        candidates = []
        for ranked_item in review_items:
            fingerprint = item_fingerprint(ranked_item.item)
            match = match_by_fingerprint[fingerprint]
            candidates.append(
                ReviewCandidate(
                    fingerprint=fingerprint,
                    item=ranked_item.item,
                    rule_score=match.score,
                    rule_topics=match.topics,
                    rule_reasons=match.reasons,
                    fallback_analysis=fallback_by_fingerprint[fingerprint],
                )
            )
        bundle = ReviewBundle(
            target_date=target_date,
            fetched_count=len(collection.fetched),
            rule_candidate_count=len(collection.matches),
            source_errors=collection.source_errors,
            collected_items=collection.deduplicated,
            candidates=candidates,
        )
        paths = write_review_bundle(self.project_root, bundle)
        return ReviewPreparationResult(
            target_date=target_date,
            bundle_path=paths.bundle_path,
            prompt_path=paths.prompt_path,
            analysis_path=paths.analysis_path,
            fetched_count=len(collection.fetched),
            rule_candidate_count=len(collection.matches),
            review_candidate_count=len(candidates),
            source_errors=collection.source_errors,
        )

    def finalize_review(
        self,
        target_date: date,
        *,
        bundle_path: str | Path | None = None,
        analysis_path: str | Path | None = None,
    ) -> PipelineResult:
        """Validate a subscription-generated review file and build final reports."""
        started = datetime.now(UTC)
        defaults = review_paths(self.project_root, target_date)
        bundle = load_review_bundle(bundle_path or defaults.bundle_path)
        submission = load_review_submission(analysis_path or defaults.analysis_path)
        if bundle.target_date != target_date:
            raise ValueError(
                f"requested date {target_date.isoformat()} does not match bundle {bundle.target_date.isoformat()}"
            )
        validate_submission(bundle, submission)
        analysis_by_fingerprint = {
            entry.fingerprint: entry.analysis for entry in submission.analyses
        }
        ranked = rank_items(
            [
                (candidate.item, analysis_by_fingerprint[candidate.fingerprint], True)
                for candidate in bundle.candidates
            ],
            self.config.ranking,
            self.config.interests,
        )
        selected = select_daily_items(
            ranked,
            self.config.interests.daily_max_recommendations,
            self.config.ranking.topic_daily_cap,
        )
        return self._persist_result(
            target_date,
            selected,
            started=started,
            fetched_count=bundle.fetched_count,
            candidate_count=bundle.rule_candidate_count,
            llm_enabled=bool(bundle.candidates),
            source_errors=bundle.source_errors,
            seen_items=bundle.collected_items,
        )

    def run(self, target_date: date, *, fixture_dir: str | Path | None = None) -> PipelineResult:
        started = datetime.now(UTC)
        collection = self._collect(target_date, fixture_dir)
        keyword = KeywordAnalyzer(self.config.interests)
        analyzed = []
        for match in collection.matches:
            fallback = keyword.analyze(match)
            analysis, used_llm = self.llm.analyze(match, fallback)
            analyzed.append((match.item, analysis, used_llm))
        ranked = rank_items(analyzed, self.config.ranking, self.config.interests)
        selected = select_daily_items(
            ranked,
            self.config.interests.daily_max_recommendations,
            self.config.ranking.topic_daily_cap,
        )
        return self._persist_result(
            target_date,
            selected,
            started=started,
            fetched_count=len(collection.fetched),
            candidate_count=len(collection.matches),
            llm_enabled=self.llm.enabled,
            source_errors=collection.source_errors,
            seen_items=collection.deduplicated,
        )
