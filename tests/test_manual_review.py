from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from cv_radar.analysis.llm import LLMAnalyzer
from cv_radar.config import load_project_config
from cv_radar.manual_review import load_review_bundle, write_review_submission
from cv_radar.models import ReviewAnalysisEntry, ReviewSubmission
from cv_radar.pipeline import RadarPipeline


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TARGET = date(2026, 7, 10)


def _pipeline(tmp_path: Path) -> RadarPipeline:
    return RadarPipeline(
        project_root=tmp_path,
        config=load_project_config(ROOT / "config"),
        llm=LLMAnalyzer(api_key=None, model=None),
    )


def _submission_for(bundle) -> ReviewSubmission:
    entries = []
    for candidate in bundle.candidates:
        analysis = candidate.fallback_analysis.model_copy(
            update={
                "summary_zh": f"Codex 订阅审阅：{candidate.item.title} 的中文概览。",
                "highlights_zh": ["亮点一：来自严格结构化人工审阅。", "亮点二：未调用 OpenAI API。"],
                "novelty_zh": "值得注意之处来自候选摘要中的方法与问题设定。",
                "core_idea": "以候选文件中的标题、摘要和元数据为依据进行保守分析。",
                "why_it_matters": "该工作命中了当前配置的计算机视觉研究兴趣。",
                "limitations": "未下载或分析完整 PDF，实验结论仍需阅读原文核对。",
                "project_connections": "可用于当前研究方向的方法和实验设计对照。",
            }
        )
        entries.append(ReviewAnalysisEntry(fingerprint=candidate.fingerprint, analysis=analysis))
    return ReviewSubmission(target_date=bundle.target_date, analyses=entries)


def test_prepare_and_finalize_review_is_idempotent(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    prepared = pipeline.prepare_review(TARGET, fixture_dir=FIXTURES)
    bundle_bytes = prepared.bundle_path.read_bytes()
    prompt_bytes = prepared.prompt_path.read_bytes()

    assert prepared.review_candidate_count == 4
    assert prepared.rule_candidate_count == 4
    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "state").exists()
    assert b"OPENAI_API_KEY" in prompt_bytes

    repeated = pipeline.prepare_review(TARGET, fixture_dir=FIXTURES)
    assert repeated.bundle_path.read_bytes() == bundle_bytes
    assert repeated.prompt_path.read_bytes() == prompt_bytes

    bundle = load_review_bundle(prepared.bundle_path)
    submission = _submission_for(bundle)
    write_review_submission(prepared.analysis_path, submission)
    first = pipeline.finalize_review(TARGET)
    first_markdown = first.markdown_path.read_bytes()
    first_pdf = first.report_path.read_bytes()
    first_seen = (tmp_path / "state" / "seen_items.jsonl").read_bytes()
    first_runs = (tmp_path / "state" / "runs.jsonl").read_bytes()

    second = pipeline.finalize_review(TARGET)
    pipeline.close()

    assert all(item.llm_analyzed for item in first.items)
    assert "Codex 订阅审阅" in first.markdown_path.read_text(encoding="utf-8")
    assert second.markdown_path.read_bytes() == first_markdown
    assert second.report_path.read_bytes() == first_pdf
    assert (tmp_path / "state" / "seen_items.jsonl").read_bytes() == first_seen
    assert (tmp_path / "state" / "runs.jsonl").read_bytes() == first_runs
    assert (tmp_path / "reports" / "latest.md").read_bytes() == first_markdown
    assert (tmp_path / "reports" / "latest.pdf").read_bytes() == first_pdf


def test_finalize_rejects_missing_candidate_analysis(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    prepared = pipeline.prepare_review(TARGET, fixture_dir=FIXTURES)
    bundle = load_review_bundle(prepared.bundle_path)
    incomplete = _submission_for(bundle).model_copy(update={"analyses": _submission_for(bundle).analyses[:-1]})
    write_review_submission(prepared.analysis_path, incomplete)

    with pytest.raises(ValueError, match="missing="):
        pipeline.finalize_review(TARGET)
    pipeline.close()

    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "state").exists()


def test_review_submission_schema_is_strict() -> None:
    with pytest.raises(ValidationError):
        ReviewSubmission.model_validate(
            {
                "schema_version": 1,
                "target_date": TARGET.isoformat(),
                "analyses": [],
                "unexpected": True,
            }
        )
