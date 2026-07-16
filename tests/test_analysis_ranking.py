from datetime import UTC, datetime

from cv_radar.analysis.keyword import KeywordAnalyzer
from cv_radar.analysis.llm import LLMAnalyzer
from cv_radar.config import InterestsConfig, RankingConfig
from cv_radar.models import ItemType, LLMAnalysis, RecommendedAction, ResearchItem
from cv_radar.processing.filtering import RuleMatch
from cv_radar.ranking import calculate_final_score, rank_items, select_daily_items


def _interests() -> InterestsConfig:
    return InterestsConfig(
        high_priority=["cell tracking"],
        medium_priority=["foundation models"],
        exploration=["world models"],
    )


def _item(source_id: str = "one", title: str = "Cell Tracking") -> ResearchItem:
    return ResearchItem(
        source="fixture",
        source_id=source_id,
        item_type=ItemType.PAPER,
        title=title,
        abstract="A novel cell tracking benchmark",
        published_at=datetime(2026, 7, 10, tzinfo=UTC),
        url=f"https://example.org/{source_id}",
    )


def _analysis(topic: str = "cell tracking", score: float = 80) -> LLMAnalysis:
    return LLMAnalysis(
        topics=[topic],
        relevance_score=score,
        novelty_score=score,
        evidence_score=score,
        reproducibility_score=score,
        summary_zh="摘要",
        highlights_zh=["亮点一", "亮点二"],
        novelty_zh="新颖性",
        core_idea="想法",
        why_it_matters="原因",
        limitations="限制",
        project_connections="联系",
        recommended_action=RecommendedAction.READ_DEEPLY,
    )


def test_ranking_calculation() -> None:
    score = calculate_final_score(_analysis(score=80), trend=40, exploration=100, config=RankingConfig())
    assert score == 79.0


def test_missing_openai_key_uses_keyword_fallback(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    match = RuleMatch(item=_item(), score=70, topics=["cell tracking"])
    fallback = KeywordAnalyzer(_interests()).analyze(match)

    result, used_llm = LLMAnalyzer.from_environment().analyze(match, fallback)

    assert result == fallback
    assert used_llm is False
    assert result.highlights_zh
    assert result.summary_zh.startswith("该论文")
    assert any(keyword in result.novelty_zh for keyword in ("创新", "新颖", "值得注意"))
    schema = LLMAnalysis.model_json_schema()
    assert schema["additionalProperties"] is False


def test_llm_failure_uses_fallback() -> None:
    class Responses:
        def parse(self, **_):
            raise RuntimeError("upstream failed")

    class Client:
        responses = Responses()

    match = RuleMatch(item=_item(), score=70, topics=["cell tracking"])
    fallback = KeywordAnalyzer(_interests()).analyze(match)
    analyzer = LLMAnalyzer(api_key="test-key", model="test-model", client=Client(), min_interval_seconds=0)

    result, used_llm = analyzer.analyze(match, fallback)

    assert result == fallback
    assert used_llm is False


def test_topic_cap_with_diverse_pool() -> None:
    analyzed = []
    topics = ["cell tracking", "cell tracking", "cell tracking", "world models", "3d vision"]
    for index, topic in enumerate(topics):
        analyzed.append((_item(str(index), f"Paper {index}"), _analysis(topic, 90 - index), False))
    ranked = rank_items(analyzed, RankingConfig(), _interests())

    selected = select_daily_items(ranked, max_items=5, topic_cap=0.4)

    assert len([item for item in selected if item.analysis.topics[0] == "cell tracking"]) <= 2
