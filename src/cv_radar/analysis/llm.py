"""Optional OpenAI Responses API analysis with strict Pydantic outputs."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from openai import OpenAI

from cv_radar.models import LLMAnalysis
from cv_radar.processing.filtering import RuleMatch

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
        min_interval_seconds: float = 0.5,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.model = model
        self.enabled = bool(api_key and model)
        self._sleep = sleeper
        self._clock = clock
        self._last_request_at: float | None = None
        self._min_interval = min_interval_seconds
        self.client = client
        if self.enabled and self.client is None:
            self.client = OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=max_retries)
        if api_key and not model:
            logger.warning("OPENAI_API_KEY is set but OPENAI_MODEL is missing; LLM analysis is disabled")

    @classmethod
    def from_environment(cls, **kwargs: Any) -> "LLMAnalyzer":
        return cls(
            api_key=os.getenv("OPENAI_API_KEY"),
            model=os.getenv("OPENAI_MODEL"),
            **kwargs,
        )

    def _pace(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            remaining = self._min_interval - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._clock()

    def analyze(self, match: RuleMatch, fallback: LLMAnalysis) -> tuple[LLMAnalysis, bool]:
        if not self.enabled:
            return fallback, False
        self._pace()
        item = match.item
        payload = {
            "title": item.title,
            "abstract": item.abstract[:8000],
            "authors": item.authors,
            "categories": item.categories,
            "venue": item.venue,
            "citation_count": item.citation_count,
            "source": item.source,
            "rule_topics": match.topics,
            "rule_reasons": match.reasons,
        }
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "你是计算机视觉研究雷达分析员。基于提供的元数据给出保守、可核查的中文分析；"
                            "不要把摘要中没有出现的实验、代码或结论当作事实。除 topics 外，所有文字字段必须使用中文。"
                            "summary_zh 用两到三句概括内容；highlights_zh 提供二到四条具体亮点；"
                            "novelty_zh 说明新颖性或值得注意之处，并区分已知事实与合理推断。所有分数范围为 0 到 100。"
                        ),
                    },
                    {"role": "user", "content": str(payload)},
                ],
                text_format=LLMAnalysis,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise ValueError("Responses API returned no parsed output")
            if not isinstance(parsed, LLMAnalysis):
                parsed = LLMAnalysis.model_validate(parsed)
            return parsed, True
        except Exception as exc:
            logger.error("OpenAI analysis failed for %s; using keyword fallback: %s", item.source_id, exc)
            return fallback, False
