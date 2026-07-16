"""Chinese Markdown report rendering."""

from __future__ import annotations

import os
from collections import OrderedDict
from datetime import date
from pathlib import Path

from cv_radar.models import ItemType, RankedItem


def _section(item: RankedItem) -> str:
    if item.item.item_type == ItemType.BLOG:
        return "博客与工程文章"
    if item.analysis.novelty_score >= 70 and item.analysis.evidence_score < 60:
        return "新颖但尚待验证"
    if item.exploration_score > 0:
        return "探索性跨领域工作"
    if item.analysis.relevance_score >= 70:
        return "高相关论文"
    return "其他值得关注"


def _render_item(ranked: RankedItem, index: int) -> str:
    item = ranked.item
    analysis = ranked.analysis
    authors = "、".join(item.authors) if item.authors else "未提供"
    topics = "、".join(analysis.topics) if analysis.topics else "未分类"
    code = f"[有]({item.code_url})" if item.code_url else "未发现"
    llm_note = "LLM" if ranked.llm_analyzed else "关键词回退"
    lines = [
            f"### {index}. {item.title}",
            "",
            f"- **作者**：{authors}",
            f"- **来源**：{item.source}",
            f"- **发布时间**：{item.published_at.date().isoformat()}",
            f"- **链接**：[原文]({item.url})" + (f" · [PDF]({item.pdf_url})" if item.pdf_url else ""),
            f"- **方向标签**：{topics}",
            f"- **综合评分**：{ranked.final_score:.2f} / 100（{llm_note}）",
            f"- **中文概览**：{analysis.summary_zh}",
            "- **亮点**：",
        ]
    lines.extend(f"  - {highlight}" for highlight in analysis.highlights_zh)
    lines.extend(
        [
            f"- **新颖或值得注意**：{analysis.novelty_zh}",
            f"- **核心想法**：{analysis.core_idea}",
            f"- **值得关注的原因**：{analysis.why_it_matters}",
            f"- **局限性**：{analysis.limitations}",
            f"- **与当前研究方向的联系**：{analysis.project_connections}",
            f"- **是否有代码**：{code}",
            f"- **建议动作**：{analysis.recommended_action.value}",
        ]
    )
    return "\n".join(lines)


def render_markdown_report(
    target_date: date,
    items: list[RankedItem],
    *,
    fetched_count: int,
    candidate_count: int,
    llm_enabled: bool,
    source_errors: list[str],
) -> str:
    lines = [
        f"# 计算机视觉研究雷达 · {target_date.isoformat()}",
        "",
        "> 自动生成的研究线索清单；分数用于排序，不替代原文阅读与实验复核。",
        "",
        "## 今日概览",
        "",
        f"- 收集条目：{fetched_count}",
        f"- 规则初筛候选：{candidate_count}",
        f"- 最终推荐：{len(items)}",
        f"- LLM 分析：{'已启用（个别失败项会自动回退）' if llm_enabled else '未执行；本报告使用关键词与元数据评分'}",
    ]
    if source_errors:
        lines.extend(["", "## 来源状态", ""])
        lines.extend(f"- ⚠️ {error}" for error in source_errors)
        lines.append("- 其余来源与日报生成已继续执行。")
    if not items:
        lines.extend(["", "## 今日推荐", "", "本日没有通过规则初筛的条目。"])
    else:
        groups: OrderedDict[str, list[RankedItem]] = OrderedDict()
        for item in items:
            groups.setdefault(_section(item), []).append(item)
        number = 1
        for section, section_items in groups.items():
            lines.extend(["", f"## {section}", ""])
            for item in section_items:
                lines.append(_render_item(item, number))
                lines.append("")
                number += 1
    lines.extend(["", "---", "", "生成管道：Fetch → Normalize → Deduplicate → Rule filter → Relevance → LLM → Rank → Report → State", ""])
    return "\n".join(lines)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def write_report(reports_dir: str | Path, target_date: date, content: str) -> Path:
    directory = Path(reports_dir)
    dated = directory / f"{target_date.isoformat()}.md"
    _atomic_text(dated, content)
    _atomic_text(directory / "latest.md", content)
    return dated
