"""Normalization, deduplication, and rule filtering."""

from cv_radar.processing.dedupe import Deduplicator, normalize_title
from cv_radar.processing.filtering import RuleFilter, RuleMatch

__all__ = ["Deduplicator", "RuleFilter", "RuleMatch", "normalize_title"]
