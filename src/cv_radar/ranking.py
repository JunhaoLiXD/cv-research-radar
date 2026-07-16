"""Weighted scoring and topic-diverse daily selection."""

from __future__ import annotations

import math

from cv_radar.config import InterestsConfig, RankingConfig
from cv_radar.models import ItemType, LLMAnalysis, RankedItem, ResearchItem


def trend_score(item: ResearchItem) -> float:
    if not item.citation_count:
        return 0.0
    return min(100.0, math.log1p(item.citation_count) * 20.0)


def exploration_score(analysis: LLMAnalysis, interests: InterestsConfig) -> float:
    exploration = {topic.casefold() for topic in interests.exploration}
    return 100.0 if any(topic.casefold() in exploration for topic in analysis.topics) else 0.0


def calculate_final_score(
    analysis: LLMAnalysis,
    trend: float,
    exploration: float,
    config: RankingConfig,
) -> float:
    weights = config.weights
    score = (
        analysis.relevance_score * weights.relevance
        + analysis.novelty_score * weights.novelty
        + analysis.evidence_score * weights.evidence
        + analysis.reproducibility_score * weights.reproducibility
        + trend * weights.trend
        + exploration * weights.exploration
    )
    return round(min(100.0, max(0.0, score)), 2)


def rank_items(
    analyzed: list[tuple[ResearchItem, LLMAnalysis, bool]],
    ranking: RankingConfig,
    interests: InterestsConfig,
) -> list[RankedItem]:
    ranked = []
    for item, analysis, llm_analyzed in analyzed:
        trend = trend_score(item)
        explore = exploration_score(analysis, interests)
        ranked.append(
            RankedItem(
                item=item,
                analysis=analysis,
                trend_score=trend,
                exploration_score=explore,
                final_score=calculate_final_score(analysis, trend, explore, ranking),
                llm_analyzed=llm_analyzed,
            )
        )
    return sorted(ranked, key=lambda value: (-value.final_score, value.item.title.casefold()))


def _theme(item: RankedItem) -> str:
    return (item.analysis.topics[0] if item.analysis.topics else "other").casefold()


def _add_if_allowed(
    selected: list[RankedItem],
    candidate: RankedItem | None,
    theme_counts: dict[str, int],
    theme_limit: int,
) -> None:
    if candidate is None or candidate in selected:
        return
    theme = _theme(candidate)
    if theme_counts.get(theme, 0) >= theme_limit:
        return
    selected.append(candidate)
    theme_counts[theme] = theme_counts.get(theme, 0) + 1


def select_daily_items(ranked: list[RankedItem], max_items: int, topic_cap: float) -> list[RankedItem]:
    if not ranked:
        return []
    target = min(max_items, len(ranked))
    theme_limit = max(1, math.floor(target * topic_cap))
    selected: list[RankedItem] = []
    theme_counts: dict[str, int] = {}

    # Seed the requested editorial mix before filling by score.
    seeds = [
        next((item for item in ranked if item.analysis.relevance_score >= 70), None),
        next((item for item in ranked if item.analysis.novelty_score >= 70 and item.analysis.evidence_score < 60), None),
        next((item for item in ranked if item.item.item_type == ItemType.BLOG), None),
        next((item for item in ranked if item.exploration_score > 0), None),
    ]
    for seed in seeds:
        if len(selected) < target:
            _add_if_allowed(selected, seed, theme_counts, theme_limit)
    for candidate in ranked:
        if len(selected) >= target:
            break
        _add_if_allowed(selected, candidate, theme_counts, theme_limit)
    return sorted(selected, key=lambda value: (-value.final_score, value.item.title.casefold()))
