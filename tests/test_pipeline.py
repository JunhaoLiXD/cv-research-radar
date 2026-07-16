from pathlib import Path

from cv_radar.analysis.llm import LLMAnalyzer
from cv_radar.config import load_project_config
from cv_radar.pipeline import RadarPipeline


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def test_same_day_fixture_run_is_idempotent(tmp_path: Path) -> None:
    config = load_project_config(ROOT / "config")
    pipeline = RadarPipeline(
        project_root=tmp_path,
        config=config,
        llm=LLMAnalyzer(api_key=None, model=None),
    )
    from datetime import date

    target = date(2026, 7, 10)
    first = pipeline.run(target, fixture_dir=FIXTURES)
    first_report = first.report_path.read_bytes()
    first_markdown = first.markdown_path.read_text(encoding="utf-8")
    first_seen_state = (tmp_path / "state" / "seen_items.jsonl").read_bytes()
    first_run_state = (tmp_path / "state" / "runs.jsonl").read_bytes()
    second = pipeline.run(target, fixture_dir=FIXTURES)
    second_report = second.report_path.read_bytes()
    pipeline.close()

    seen_lines = (tmp_path / "state" / "seen_items.jsonl").read_text(encoding="utf-8").splitlines()
    run_lines = (tmp_path / "state" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert first_report == second_report
    assert (tmp_path / "state" / "seen_items.jsonl").read_bytes() == first_seen_state
    assert (tmp_path / "state" / "runs.jsonl").read_bytes() == first_run_state
    assert len(seen_lines) == 4
    assert len(run_lines) == 1
    assert len(second.items) == 4
    assert all(item.analysis.summary_zh for item in second.items)
    assert all(item.analysis.highlights_zh for item in second.items)
    assert all(item.analysis.novelty_zh for item in second.items)
    assert second.report_path.suffix == ".pdf"
    assert (tmp_path / "reports" / "latest.pdf").read_bytes() == second_report
    assert (tmp_path / "reports" / "latest.md").read_text(encoding="utf-8") == first_markdown
