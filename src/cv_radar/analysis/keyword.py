"""Deterministic analysis used as the baseline and no-key fallback."""

from __future__ import annotations

import math

from cv_radar.config import InterestsConfig
from cv_radar.models import ItemType, LLMAnalysis, RecommendedAction
from cv_radar.processing.filtering import RuleMatch


class KeywordAnalyzer:
    def __init__(self, interests: InterestsConfig) -> None:
        self.interests = interests

    def analyze(self, match: RuleMatch) -> LLMAnalysis:
        item = match.item
        text = f"{item.title} {item.abstract}".casefold()
        exploration_hits = [topic for topic in match.topics if topic in self.interests.exploration]
        novelty = 50.0 + min(25.0, len(exploration_hits) * 15.0)
        if any(token in text for token in ("novel", "first", "new framework", "introduce")):
            novelty += 10.0
        evidence = 35.0 if item.item_type == ItemType.PAPER else 25.0
        if item.venue:
            evidence += 20.0
        if item.citation_count:
            evidence += min(25.0, math.log1p(item.citation_count) * 7.0)
        if any(token in text for token in ("benchmark", "dataset", "evaluation")):
            evidence += 10.0
        reproducibility = 15.0
        if item.pdf_url:
            reproducibility += 20.0
        if item.code_url:
            reproducibility += 50.0
        elif "code" in str(item.raw_metadata).casefold():
            reproducibility += 15.0
        relevance = min(100.0, match.score)
        if relevance >= 75 and evidence >= 45:
            action = RecommendedAction.READ_DEEPLY
        elif relevance >= 45:
            action = RecommendedAction.BROWSE
        elif novelty >= 70:
            action = RecommendedAction.WATCH
        else:
            action = RecommendedAction.SKIP
        topic_text = "、".join(match.topics) if match.topics else "计算机视觉"
        item_label = {
            ItemType.PAPER: "论文",
            ItemType.BLOG: "文章",
            ItemType.REPOSITORY: "项目",
            ItemType.DATASET: "数据集",
            ItemType.TOOL: "工具",
        }[item.item_type]
        signals: list[str] = []
        if "tracking" in text:
            signals.append("目标跟踪")
        if "segmentation" in text:
            signals.append("图像分割")
        if "foundation model" in text:
            signals.append("视觉基础模型")
        if "world model" in text:
            signals.append("世界模型")
        if "benchmark" in text or "evaluation" in text:
            signals.append("基准评测")
        method_text = "、".join(dict.fromkeys(signals)) or topic_text
        highlights = [f"与当前关注的{topic_text}方向直接相关。"]
        if item.pdf_url:
            highlights.append("提供可直接阅读的 PDF，便于进一步核查方法和实验细节。")
        if item.code_url:
            highlights.append("已发现代码链接，具备进一步复现和工程验证的条件。")
        elif "code" in str(item.raw_metadata).casefold():
            highlights.append("元数据中出现代码相关信号，但仍需打开原文确认代码是否已公开。")
        if item.venue:
            highlights.append(f"已有 {item.venue} 发表或收录信息，可作为证据质量参考。")
        if exploration_hits:
            highlights.append(f"覆盖探索方向：{'、'.join(exploration_hits)}。")
        if len(highlights) == 1:
            highlights.append("标题和摘要提供了明确的研究主题，可用于快速判断是否值得深入阅读。")
        novelty_signal = any(token in text for token in ("novel", "first", "new framework", "introduce"))
        if novelty_signal:
            novelty_zh = "标题或摘要包含新方法、新框架或首次探索的表述，可能具有方法创新；具体创新幅度仍需对照原文和相关工作确认。"
        elif exploration_hits:
            novelty_zh = f"值得注意之处是将{topic_text}纳入探索性方向，可能带来跨领域方法迁移价值。"
        else:
            novelty_zh = f"现有元数据不足以确认独创性；目前最值得注意的是其围绕{method_text}提供了新的研究或实践线索。"
        return LLMAnalysis(
            topics=match.topics or item.categories[:3] or ["computer vision"],
            relevance_score=relevance,
            novelty_score=min(100.0, novelty),
            evidence_score=min(100.0, evidence),
            reproducibility_score=min(100.0, reproducibility),
            summary_zh=f"该{item_label}聚焦于{topic_text}，主要涉及{method_text}。当前结论来自标题、摘要和元数据，适合作为阅读前的快速导览。",
            highlights_zh=highlights[:5],
            novelty_zh=novelty_zh,
            core_idea=f"围绕{method_text}开展方法、系统或工程探索；具体技术设计与实验结论需要结合原文进一步确认。",
            why_it_matters="命中了当前研究兴趣配置，值得按综合评分进一步判断。",
            limitations="未执行 LLM 深度分析；结论仅来自关键词、元数据和规则评分。",
            project_connections=f"可与当前关注的{topic_text}方向进行方法、数据或实验对照。",
            recommended_action=action,
        )
