"""Polished Chinese PDF report generation."""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    CondPageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from cv_radar.models import ItemType, RankedItem

PDF_FONT = "STSong-Light"


def _register_font() -> None:
    try:
        pdfmetrics.getFont(PDF_FONT)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))


def _styles() -> dict[str, ParagraphStyle]:
    _register_font()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "RadarTitle",
            parent=base["Title"],
            fontName=PDF_FONT,
            fontSize=20,
            leading=28,
            textColor=colors.HexColor("#17324D"),
            alignment=TA_CENTER,
            spaceAfter=5 * mm,
        ),
        "subtitle": ParagraphStyle(
            "RadarSubtitle",
            fontName=PDF_FONT,
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#566573"),
            alignment=TA_CENTER,
            spaceAfter=5 * mm,
        ),
        "section": ParagraphStyle(
            "RadarSection",
            fontName=PDF_FONT,
            fontSize=14,
            leading=20,
            textColor=colors.HexColor("#17324D"),
            spaceBefore=4 * mm,
            spaceAfter=3 * mm,
        ),
        "item_title": ParagraphStyle(
            "RadarItemTitle",
            fontName=PDF_FONT,
            fontSize=12.5,
            leading=18,
            textColor=colors.HexColor("#1F5D7A"),
            spaceAfter=2.5 * mm,
        ),
        "body": ParagraphStyle(
            "RadarBody",
            fontName=PDF_FONT,
            fontSize=9.5,
            leading=15,
            textColor=colors.HexColor("#263238"),
            alignment=TA_LEFT,
            spaceAfter=1.5 * mm,
        ),
        "label": ParagraphStyle(
            "RadarLabel",
            fontName=PDF_FONT,
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#35647A"),
        ),
        "meta": ParagraphStyle(
            "RadarMeta",
            fontName=PDF_FONT,
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#34495E"),
        ),
        "highlight": ParagraphStyle(
            "RadarHighlight",
            fontName=PDF_FONT,
            fontSize=9.5,
            leading=15,
            leftIndent=4 * mm,
            firstLineIndent=-3 * mm,
            textColor=colors.HexColor("#263238"),
            spaceAfter=1 * mm,
        ),
        "notice": ParagraphStyle(
            "RadarNotice",
            fontName=PDF_FONT,
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#7A4E00"),
        ),
    }


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


def _safe(value: object) -> str:
    return escape(str(value or ""), {'"': "&quot;"})


def _mixed(value: object) -> str:
    """Use Helvetica for Latin runs to avoid CID-font spacing artifacts."""
    parts = re.split(r"([\x20-\x7E]+)", str(value or ""))
    rendered: list[str] = []
    for part in parts:
        if not part:
            continue
        safe = escape(part, {'"': "&quot;"})
        if all(" " <= character <= "~" for character in part):
            rendered.append(f'<font name="Helvetica">{safe}</font>')
        else:
            rendered.append(safe)
    return "".join(rendered)


def _link(url: str | None, label: str) -> str:
    if not url:
        return ""
    return f'<link href="{_safe(url)}" color="#1F6F9B"><u>{_mixed(label)}</u></link>'


def _page_decorator(target_date: date):
    def draw(canvas: pdfcanvas.Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor("#D6E1E7"))
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, height - 14 * mm, width - doc.rightMargin, height - 14 * mm)
        canvas.setFont(PDF_FONT, 8)
        canvas.setFillColor(colors.HexColor("#607D8B"))
        canvas.drawString(doc.leftMargin, height - 11 * mm, f"计算机视觉研究雷达 | {target_date.isoformat()}")
        canvas.drawRightString(width - doc.rightMargin, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    return draw


def _invariant_canvas(*args, **kwargs):
    kwargs["invariant"] = 1
    kwargs["pageCompression"] = 1
    return pdfcanvas.Canvas(*args, **kwargs)


def _metadata_table(ranked: RankedItem, styles: dict[str, ParagraphStyle]) -> Table:
    item = ranked.item
    analysis = ranked.analysis
    authors = "、".join(item.authors) if item.authors else "未提供"
    topics = "、".join(analysis.topics) if analysis.topics else "未分类"
    mode = "LLM 深度分析" if ranked.llm_analyzed else "关键词回退"
    links = " | ".join(
        value
        for value in (
            _link(item.url, "原文"),
            _link(item.pdf_url, "PDF"),
            _link(item.code_url, "代码"),
        )
        if value
    )
    rows = [
        [Paragraph("作者", styles["label"]), Paragraph(_mixed(authors), styles["meta"])],
        [Paragraph("来源与日期", styles["label"]), Paragraph(_mixed(f"{item.source} | {item.published_at.date().isoformat()}"), styles["meta"])],
        [Paragraph("方向标签", styles["label"]), Paragraph(_mixed(topics), styles["meta"])],
        [Paragraph("评分", styles["label"]), Paragraph(_mixed(f"{ranked.final_score:.2f} / 100 | {mode} | 建议：{analysis.recommended_action.value}"), styles["meta"])],
        [Paragraph("链接", styles["label"]), Paragraph(links or "未提供", styles["meta"])],
    ]
    table = Table(rows, colWidths=[29 * mm, 141 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F7F9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#D8E3E8")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD8DE")),
            ]
        )
    )
    return table


def _labeled(story: list, label: str, value: str, styles: dict[str, ParagraphStyle]) -> None:
    story.append(Paragraph(_mixed(label), styles["label"]))
    story.append(Paragraph(_mixed(value), styles["body"]))


def write_pdf_report(
    output_dir: str | Path,
    target_date: date,
    items: list[RankedItem],
    *,
    fetched_count: int,
    candidate_count: int,
    llm_enabled: bool,
    source_errors: list[str],
) -> Path:
    styles = _styles()
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    dated = directory / f"{target_date.isoformat()}.pdf"
    temp = dated.with_suffix(".pdf.tmp")
    doc = SimpleDocTemplate(
        str(temp),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=23 * mm,
        bottomMargin=18 * mm,
        title=f"计算机视觉研究雷达 {target_date.isoformat()}",
        author="cv-research-radar",
    )
    story: list = [
        Paragraph(_mixed(f"计算机视觉研究雷达 · {target_date.isoformat()}"), styles["title"]),
        Paragraph(_mixed("自动生成的研究线索清单。中文总结用于快速导览，不替代原文阅读与实验复核。"), styles["subtitle"]),
    ]
    overview = Table(
        [
            [Paragraph("收集条目", styles["label"]), Paragraph("初筛候选", styles["label"]), Paragraph("最终推荐", styles["label"])],
            [Paragraph(_mixed(fetched_count), styles["section"]), Paragraph(_mixed(candidate_count), styles["section"]), Paragraph(_mixed(len(items)), styles["section"])],
        ],
        colWidths=[56.5 * mm] * 3,
    )
    overview.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EDF4F7")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9D9E0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8E3E8")),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ]
        )
    )
    story.extend(
        [
            overview,
            Spacer(1, 3 * mm),
            Paragraph(
                _mixed("LLM 分析：已启用，个别失败项自动回退。" if llm_enabled else "LLM 分析：未执行，本报告使用中文关键词与元数据回退总结。"),
                styles["notice"],
            ),
        ]
    )
    if source_errors:
        story.append(Paragraph("来源状态", styles["section"]))
        for error in source_errors:
            story.append(Paragraph(_mixed(f"- {error}"), styles["notice"]))
        story.append(Paragraph("其余来源和报告生成已继续执行。", styles["notice"]))
    if not items:
        story.extend([Paragraph("今日推荐", styles["section"]), Paragraph("本日没有通过规则初筛的条目。", styles["body"])])
    else:
        groups: OrderedDict[str, list[RankedItem]] = OrderedDict()
        for ranked in items:
            groups.setdefault(_section(ranked), []).append(ranked)
        number = 1
        for section, section_items in groups.items():
            story.append(CondPageBreak(120 * mm))
            story.append(Paragraph(_safe(section), styles["section"]))
            for ranked in section_items:
                analysis = ranked.analysis
                story.extend(
                    [
                        CondPageBreak(105 * mm),
                        Paragraph(_mixed(f"{number}. {ranked.item.title}"), styles["item_title"]),
                        _metadata_table(ranked, styles),
                        Spacer(1, 2.5 * mm),
                    ]
                )
                _labeled(story, "中文概览", analysis.summary_zh, styles)
                story.append(Paragraph("亮点", styles["label"]))
                for highlight in analysis.highlights_zh:
                    story.append(Paragraph(_mixed(f"- {highlight}"), styles["highlight"]))
                _labeled(story, "新颖或值得注意", analysis.novelty_zh, styles)
                _labeled(story, "核心想法", analysis.core_idea, styles)
                _labeled(story, "为什么值得关注", analysis.why_it_matters, styles)
                _labeled(story, "局限性", analysis.limitations, styles)
                _labeled(story, "与当前研究方向的联系", analysis.project_connections, styles)
                story.append(Spacer(1, 4 * mm))
                number += 1
    story.extend(
        [
            Spacer(1, 4 * mm),
            Paragraph(_mixed("生成管道：Fetch -> Normalize -> Deduplicate -> Rule filter -> LLM -> Rank -> PDF -> State"), styles["notice"]),
        ]
    )
    decorator = _page_decorator(target_date)
    doc.build(story, onFirstPage=decorator, onLaterPages=decorator, canvasmaker=_invariant_canvas)
    temp.replace(dated)
    latest = directory / "latest.pdf"
    latest_temp = latest.with_suffix(".pdf.tmp")
    with dated.open("rb") as source, latest_temp.open("wb") as target:
        target.write(source.read())
        target.flush()
        os.fsync(target.fileno())
    latest_temp.replace(latest)
    return dated
