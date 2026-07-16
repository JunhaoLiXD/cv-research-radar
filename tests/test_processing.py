from datetime import UTC, datetime

from cv_radar.config import InterestsConfig
from cv_radar.models import ItemType, ResearchItem
from cv_radar.processing.dedupe import Deduplicator, normalize_title
from cv_radar.processing.filtering import RuleFilter


def _item(source_id: str, title: str, *, doi: str | None = None) -> ResearchItem:
    external = {"DOI": doi} if doi else {}
    return ResearchItem(
        source="test",
        source_id=source_id,
        item_type=ItemType.PAPER,
        title=title,
        abstract="A microscopy cell tracking method",
        published_at=datetime(2026, 7, 10, tzinfo=UTC),
        url=f"https://example.org/{source_id}",
        raw_metadata={"external_ids": external},
    )


def test_normalize_title() -> None:
    assert normalize_title("  Vision: A Test! ") == "vision a test"
    assert normalize_title("Ｆｏｕｎｄａｔｉｏｎ Models") == "foundation models"


def test_deduplicate_by_stable_id() -> None:
    items = [
        _item("one", "First title", doi="https://doi.org/10.1/ABC"),
        _item("two", "A renamed preprint", doi="10.1/abc"),
    ]
    assert len(Deduplicator().deduplicate(items)) == 1


def test_deduplicate_by_fuzzy_title() -> None:
    items = [
        _item("one", "Foundation Models for Microscopy Cell Tracking"),
        _item("two", "Foundation Model for Microscopy Cell Tracking"),
    ]
    assert len(Deduplicator(fuzzy_threshold=90).deduplicate(items)) == 1


def test_rule_filter_and_exclusion() -> None:
    interests = InterestsConfig(
        high_priority=["cell tracking"],
        medium_priority=["foundation models"],
        exploration=[],
        exclude_keywords=["withdrawn"],
    )
    filterer = RuleFilter(interests, minimum_score=15)

    assert filterer.evaluate(_item("one", "Cell Tracking in Microscopy")) is not None
    withdrawn = _item("two", "Withdrawn Cell Tracking Paper")
    assert filterer.evaluate(withdrawn) is None
