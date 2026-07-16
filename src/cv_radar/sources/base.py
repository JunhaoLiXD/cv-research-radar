from __future__ import annotations

from dataclasses import dataclass, field

from cv_radar.models import ResearchItem


@dataclass(slots=True)
class FetchResult:
    items: list[ResearchItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
