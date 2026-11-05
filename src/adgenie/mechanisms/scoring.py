"""机制二：双标尺评分。

- 需求对齐度（代码集合运算，不调模型）：关键词命中/集合运算。
- 转化说服力（模型 rubric 逐项打分，Judge 温度=0）。
- 两尺独立计算再合成，禁止合并成单一总分；扣分必须溯源到证据位置。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from adgenie.models import LLMClient

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "be", "it", "this", "that", "very",
    "so", "just", "not", "no", "yes", "at", "by", "from", "as", "we", "you",
    "they", "i", "he", "she", "my", "your", "our", "their",
}

# 转化说服力 rubric（版本化）
PERSUASION_RUBRIC: dict[str, List[str]] = {
    "v1": [
        "relevance",          # 与用户关注点相关
        "clarity",            # 表达清晰
        "specificity",        # 具体、有证据支撑
        "persuasiveness",     # 说服力/情感打动
        "call_to_action",     # 行动号召
    ],
}


def extract_keywords(text: str) -> set[str]:
    """纯代码关键词抽取：小写、分词、去停用词。"""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if len(t) > 1 and t not in _STOPWORDS}


@dataclass
class AlignmentDetail:
    score: float
    matched: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


def compute_alignment(copy_text: str, concern_keywords: List[str]) -> AlignmentDetail:
    """需求对齐度：集合运算，不调模型。"""
    copy_kw = extract_keywords(copy_text)
    matched = [k for k in concern_keywords if k in copy_kw]
    missing = [k for k in concern_keywords if k not in copy_kw]
    score = len(matched) / len(concern_keywords) if concern_keywords else 1.0
    return AlignmentDetail(score=round(score, 4), matched=matched, missing=missing)


@dataclass
class PersuasionDetail:
    score: float
    items: List[dict] = field(default_factory=list)


def build_persuasion_prompt(rubric_version: str, copy: str,
                            evidences: List[dict]) -> str:
    dimensions = PERSUASION_RUBRIC.get(rubric_version, PERSUASION_RUBRIC["v1"])
    dims = ", ".join(f'"{d}"' for d in dimensions)
    evidence_lines = "\n".join(
        f"- {e.get('review_id')}: {e.get('quote', '')}" for e in evidences
    )
    return (
        "你是广告文案评分裁判。请对下面这条广告文案，按 rubric 逐项打分。\n"
        f"rubric 维度（版本 {rubric_version}）：{dims}\n"
        "每项给出 0-1 分数；若有扣分，必须给出 item、reason、evidence_ref（评论编号）。\n"
        "只输出 JSON，不要输出其他文字，格式：\n"
        '{"score": 0.82, "items": [{"dimension": "relevance", "score": 0.9, '
        '"deductions": [{"item": "...", "reason": "...", "evidence_ref": "R-001"}]}]}\n\n'
        f"【证据】\n{evidence_lines}\n\n"
        f"【广告文案】\n{copy}\n"
    )


def score_persuasion(judge: LLMClient, rubric_version: str, copy: str,
                     evidences: List[dict]) -> PersuasionDetail:
    """转化说服力：模型 rubric 逐项打分。Judge 侧 temperature 必须为 0。"""
    if judge.temperature != 0.0:
        raise ValueError("Judge 侧 temperature 必须为 0，禁止修改")
    prompt = build_persuasion_prompt(rubric_version, copy, evidences)
    result = judge.complete_json(prompt)
    if not isinstance(result, dict) or "score" not in result:
        raise ValueError(f"Judge 输出 schema 非法：{result!r}")
    items = result.get("items", [])
    score = float(result["score"])
    return PersuasionDetail(score=round(score, 4), items=items)
