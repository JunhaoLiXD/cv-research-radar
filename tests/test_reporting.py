from datetime import UTC, date, datetime

from cv_radar.models import ItemType, LLMAnalysis, RankedItem, RecommendedAction, ResearchItem
from cv_radar.pdf_reporting import write_pdf_report
from cv_radar.reporting import render_markdown_report
from pypdf import PdfReader


def test_markdown_report_contains_required_fields() -> None:
    item = ResearchItem(
        source="arXiv",
        source_id="arxiv:1",
        item_type=ItemType.PAPER,
        title="English Paper Title",
        abstract="abstract",
        authors=["Ada"],
        published_at=datetime(2026, 7, 10, tzinfo=UTC),
        url="https://example.org/paper",
        pdf_url="https://example.org/paper.pdf",
        code_url="https://github.com/example/code",
    )
    analysis = LLMAnalysis(
        topics=["cell tracking"],
        relevance_score=90,
        novelty_score=80,
        evidence_score=70,
        reproducibility_score=80,
        summary_zh="摘要",
        highlights_zh=["亮点一", "亮点二"],
        novelty_zh="这是值得注意的新颖之处。",
        core_idea="核心",
        why_it_matters="原因",
        limitations="局限",
        project_connections="联系",
        recommended_action=RecommendedAction.READ_DEEPLY,
    )
    ranked = RankedItem(
        item=item,
        analysis=analysis,
        trend_score=10,
        exploration_score=0,
        final_score=82.5,
        llm_analyzed=True,
    )

    report = render_markdown_report(
        date(2026, 7, 10), [ranked], fetched_count=1, candidate_count=1, llm_enabled=True, source_errors=[]
    )

    assert "English Paper Title" in report
    assert "**综合评分**：82.50" in report
    assert "**中文概览**：摘要" in report
    assert "亮点一" in report
    assert "**新颖或值得注意**" in report
    assert "**核心想法**：核心" in report
    assert "**是否有代码**：[有]" in report
    assert "**建议动作**：精读" in report


def test_pdf_report_contains_chinese_analysis(tmp_path) -> None:
    item = ResearchItem(
        source="arXiv",
        source_id="arxiv:1",
        item_type=ItemType.PAPER,
        title="English Paper Title",
        abstract="abstract",
        authors=["Ada"],
        published_at=datetime(2026, 7, 10, tzinfo=UTC),
        url="https://example.org/paper",
        pdf_url="https://example.org/paper.pdf",
    )
    analysis = LLMAnalysis(
        topics=["cell tracking"],
        relevance_score=90,
        novelty_score=80,
        evidence_score=70,
        reproducibility_score=80,
        summary_zh="这是一段中文概览。",
        highlights_zh=["亮点一：关注细胞跟踪。", "亮点二：提供实验线索。"],
        novelty_zh="新颖之处在于方法组合。",
        core_idea="核心想法使用中文表达。",
        why_it_matters="与当前研究方向相关。",
        limitations="仍需核对原文。",
        project_connections="可以用于方法对照。",
        recommended_action=RecommendedAction.READ_DEEPLY,
    )
    ranked = RankedItem(
        item=item,
        analysis=analysis,
        trend_score=10,
        exploration_score=0,
        final_score=82.5,
        llm_analyzed=True,
    )

    path = write_pdf_report(
        tmp_path / "reports",
        date(2026, 7, 10),
        [ranked],
        fetched_count=1,
        candidate_count=1,
        llm_enabled=True,
        source_errors=[],
    )
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert path.suffix == ".pdf"
    assert len(reader.pages) >= 1
    assert "English Paper Title" in text
    assert "中文概览" in text
    assert (path.parent / "latest.pdf").read_bytes() == path.read_bytes()
