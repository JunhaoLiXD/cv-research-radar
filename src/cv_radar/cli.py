"""Typer command-line interface."""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

from cv_radar.analysis import LLMAnalyzer
from cv_radar.config import load_project_config
from cv_radar.pipeline import RadarPipeline

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(no_args_is_help=True, help="每日计算机视觉研究雷达")


def _today_configured() -> date:
    from datetime import datetime

    timezone_name = os.getenv("RADAR_TIMEZONE", "America/New_York")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise typer.BadParameter(f"RADAR_TIMEZONE 不是有效 IANA 时区: {timezone_name}") from exc
    return datetime.now(timezone).date()


def _parse_date(value: str | None) -> date:
    if value is None:
        return _today_configured()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("日期必须为 YYYY-MM-DD") from exc


def _run_one(target: date, root: Path, config_dir: Path, fixture_dir: Path | None) -> None:
    pipeline = RadarPipeline(project_root=root, config_dir=config_dir)
    try:
        result = pipeline.run(target, fixture_dir=fixture_dir)
    finally:
        pipeline.close()
    typer.echo(
        f"{target.isoformat()}: fetched={result.fetched_count}, candidates={result.candidate_count}, "
        f"recommended={len(result.items)}, report={result.report_path}"
    )
    for error in result.source_errors:
        typer.echo(f"warning: {error}", err=True)


def _resolve_optional_path(root: Path, value: Path | None) -> Path | None:
    if value is None or value.is_absolute():
        return value
    return root / value


@app.command("run")
def run_command(
    date_value: str | None = typer.Option(None, "--date", help="目标日期 YYYY-MM-DD"),
    root: Path = typer.Option(Path("."), help="报告和状态输出根目录"),
    config_dir: Path = typer.Option(Path("config"), help="配置目录；相对路径以 root 为基准"),
    fixture_dir: Path | None = typer.Option(None, help="离线验收 fixture 目录，不发起网络请求"),
) -> None:
    """收集并生成单日研究雷达。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _run_one(_parse_date(date_value), root, config_dir, fixture_dir)


@app.command("prepare-review")
def prepare_review_command(
    date_value: str | None = typer.Option(None, "--date", help="目标日期 YYYY-MM-DD"),
    root: Path = typer.Option(Path("."), help="项目根目录"),
    config_dir: Path = typer.Option(Path("config"), help="配置目录；相对路径以 root 为基准"),
    fixture_dir: Path | None = typer.Option(None, help="离线 fixture 目录，不发起网络请求"),
) -> None:
    """抓取并导出供 ChatGPT/Codex 订阅审阅的候选材料，不调用 OpenAI API。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    target = _parse_date(date_value)
    pipeline = RadarPipeline(
        project_root=root,
        config_dir=config_dir,
        llm=LLMAnalyzer(api_key=None, model=None),
    )
    try:
        result = pipeline.prepare_review(target, fixture_dir=fixture_dir)
    finally:
        pipeline.close()
    typer.echo(
        f"{target.isoformat()}: fetched={result.fetched_count}, "
        f"rule_candidates={result.rule_candidate_count}, review_candidates={result.review_candidate_count}"
    )
    typer.echo(f"candidates={result.bundle_path}")
    typer.echo(f"prompt={result.prompt_path}")
    typer.echo(f"expected_analysis={result.analysis_path}")
    for error in result.source_errors:
        typer.echo(f"warning: {error}", err=True)


@app.command("finalize-review")
def finalize_review_command(
    date_value: str | None = typer.Option(None, "--date", help="目标日期 YYYY-MM-DD"),
    root: Path = typer.Option(Path("."), help="项目根目录"),
    config_dir: Path = typer.Option(Path("config"), help="配置目录；相对路径以 root 为基准"),
    bundle_file: Path | None = typer.Option(None, "--bundle-file", help="候选 bundle；默认按日期查找"),
    analysis_file: Path | None = typer.Option(None, "--analysis-file", help="Codex 分析 JSON；默认按日期查找"),
) -> None:
    """校验订阅审阅结果，重新排名并生成最终 Markdown/PDF。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    target = _parse_date(date_value)
    pipeline = RadarPipeline(
        project_root=root,
        config_dir=config_dir,
        llm=LLMAnalyzer(api_key=None, model=None),
    )
    try:
        result = pipeline.finalize_review(
            target,
            bundle_path=_resolve_optional_path(root, bundle_file),
            analysis_path=_resolve_optional_path(root, analysis_file),
        )
    finally:
        pipeline.close()
    typer.echo(
        f"{target.isoformat()}: candidates={result.candidate_count}, "
        f"recommended={len(result.items)}, markdown={result.markdown_path}, pdf={result.report_path}"
    )


@app.command()
def backfill(
    days: int = typer.Option(..., min=1, max=365, help="包含今天在内的回填天数"),
    root: Path = typer.Option(Path(".")),
    config_dir: Path = typer.Option(Path("config")),
) -> None:
    """逐日回填最近 N 天；每一天独立生成并幂等写入。"""
    today = _today_configured()
    for offset in reversed(range(days)):
        _run_one(today - timedelta(days=offset), root, config_dir, None)


@app.command("validate-config")
def validate_config(config_dir: Path = typer.Option(Path("config"))) -> None:
    """加载并严格校验全部 YAML 配置。"""
    config = load_project_config(config_dir)
    typer.echo(
        f"配置有效：{len(config.sources.arxiv.categories)} 个 arXiv 分类，"
        f"{len(config.sources.feeds)} 个 Feed，日报上限 {config.interests.daily_max_recommendations}"
    )


@app.command("list-sources")
def list_sources(config_dir: Path = typer.Option(Path("config"))) -> None:
    """列出启用状态和来源地址。"""
    config = load_project_config(config_dir)
    typer.echo(f"arXiv [{'on' if config.sources.arxiv.enabled else 'off'}]: {', '.join(config.sources.arxiv.categories)}")
    typer.echo(f"Semantic Scholar [{'on' if config.sources.semantic_scholar.enabled else 'off'}]")
    for feed in config.sources.feeds:
        typer.echo(f"Feed [{'on' if feed.enabled else 'off'}] {feed.name}: {feed.url}")
