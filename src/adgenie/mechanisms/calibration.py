"""机制三：构造式评分校准。

- 主扰动：埋入已知缺陷（应被检出）。
- 安慰剂：无缺陷优质文案（不应被误报）。
- 检出率与误判率必须分开报告，并经置换检验给出 p 值；禁止只报单一准确率。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

from adgenie.data.domain import CalibrationReport
from adgenie.models import LLMClient
from adgenie.mechanisms.scoring import score_persuasion


def inject_defect(copy: str, defect_type: str, concern_keywords: List[str]) -> str:
    """埋入已知缺陷。返回带缺陷的文案。"""
    if defect_type == "missing_key_concern":
        keyword = concern_keywords[0] if concern_keywords else "quality"
        return copy.replace(keyword, "", 1).strip()
    if defect_type == "contradicts_evidence":
        return copy + " (This claim is contradicted by verified customer reviews.)"
    raise ValueError(f"未知缺陷类型：{defect_type}")


def _is_detected(judge: LLMClient, rubric_version: str, copy: str,
                 evidences: List[dict], quality_threshold: float) -> bool:
    persuasion = score_persuasion(judge, rubric_version, copy, evidences)
    return persuasion.score < quality_threshold


def permutation_test(perturbed_detected: List[bool], placebo_detected: List[bool],
                     iterations: int, seed: int) -> float:
    """置换检验：计算两组检出率差异的 p 值。"""
    rng = random.Random(seed)
    observed = _rate_diff(perturbed_detected, placebo_detected)
    pool = perturbed_detected + placebo_detected
    n_p = len(perturbed_detected)
    count = 0
    for _ in range(iterations):
        shuffled = pool[:]
        rng.shuffle(shuffled)
        a = shuffled[:n_p]
        b = shuffled[n_p:]
        if _rate_diff(a, b) >= observed:
            count += 1
    return (count + 1) / (iterations + 1)  # 平滑，避免 p=0


def _rate_diff(a: List[bool], b: List[bool]) -> float:
    rate_a = sum(a) / len(a) if a else 0.0
    rate_b = sum(b) / len(b) if b else 0.0
    return rate_a - rate_b


@dataclass
class CalibrationResult:
    report: CalibrationReport
    perturbed_detected: List[bool]
    placebo_detected: List[bool]


def run_calibration(
    judge: LLMClient,
    rubric_version: str,
    base_copy: str,
    concern_keywords: List[str],
    evidences: List[dict],
    defect_types: List[str],
    n_perturbed: int,
    n_placebo: int,
    quality_threshold: float,
    permutation_iterations: int,
    seed: int,
) -> CalibrationResult:
    """运行构造式校准，返回检出率/误判率/p 值。"""
    rng = random.Random(seed)
    perturbed_detected: List[bool] = []
    for i in range(n_perturbed):
        defect = defect_types[i % len(defect_types)]
        perturbed = inject_defect(base_copy, defect, concern_keywords)
        perturbed_detected.append(
            _is_detected(judge, rubric_version, perturbed, evidences, quality_threshold))

    placebo_detected: List[bool] = []
    for _ in range(n_placebo):
        # 安慰剂：无缺陷优质文案（可做轻微无害改写，保持语义）
        placebo = base_copy
        placebo_detected.append(
            _is_detected(judge, rubric_version, placebo, evidences, quality_threshold))

    detection_rate = sum(perturbed_detected) / len(perturbed_detected)
    false_alarm_rate = sum(placebo_detected) / len(placebo_detected)
    p_value = permutation_test(perturbed_detected, placebo_detected,
                               permutation_iterations, seed)

    report = CalibrationReport(
        detection_rate=round(detection_rate, 4),
        false_alarm_rate=round(false_alarm_rate, 4),
        p_value=round(p_value, 6),
        n_perturbed=n_perturbed,
        n_placebo=n_placebo,
        rubric_version=rubric_version,
    )
    return CalibrationResult(report=report,
                             perturbed_detected=perturbed_detected,
                             placebo_detected=placebo_detected)
