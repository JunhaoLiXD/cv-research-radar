"""Explainable rule-based filtering before any LLM call."""

from __future__ import annotations

from dataclasses import dataclass, field

from cv_radar.config import InterestsConfig
from cv_radar.models import ResearchItem


@dataclass(slots=True)
class RuleMatch:
    item: ResearchItem
    score: float
    topics: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _matches(phrases: list[str], text: str) -> list[str]:
    return [phrase for phrase in phrases if phrase.casefold() in text]


class RuleFilter:
    def __init__(self, interests: InterestsConfig, minimum_score: float) -> None:
        self.interests = interests
        self.minimum_score = minimum_score

    def evaluate(self, item: ResearchItem) -> RuleMatch | None:
        text = " ".join([item.title, item.abstract, *item.categories, item.venue or ""]).casefold()
        excluded = _matches(self.interests.exclude_keywords, text)
        if excluded:
            return None
        high = _matches(self.interests.high_priority, text)
        medium = _matches(self.interests.medium_priority, text)
        exploration = _matches(self.interests.exploration, text)
        author_text = " ".join(item.authors).casefold()
        followed_authors = _matches(self.interests.followed_authors, author_text)
        venue_text = (item.venue or "").casefold()
        followed_venues = _matches(self.interests.followed_venues, venue_text)
        score = min(
            100.0,
            min(len(high), 2) * 35.0
            + min(len(medium), 2) * 20.0
            + min(len(exploration), 2) * 15.0
            + (25.0 if followed_authors else 0.0)
            + (20.0 if followed_venues else 0.0),
        )
        if score < self.minimum_score:
            return None
        topics = list(dict.fromkeys([*high, *medium, *exploration]))
        reasons = []
        if high:
            reasons.append(f"高优先级命中：{', '.join(high)}")
        if medium:
            reasons.append(f"中优先级命中：{', '.join(medium)}")
        if exploration:
            reasons.append(f"探索方向命中：{', '.join(exploration)}")
        if followed_authors:
            reasons.append(f"关注作者：{', '.join(followed_authors)}")
        if followed_venues:
            reasons.append(f"关注会议：{', '.join(followed_venues)}")
        return RuleMatch(item=item, score=score, topics=topics, reasons=reasons)

    def filter(self, items: list[ResearchItem]) -> list[RuleMatch]:
        return [match for item in items if (match := self.evaluate(item)) is not None]
