"""机制一：证据锚定与编号白名单。

- 每条用户关注点必须携带「评论编号 + 原文引用」。
- 白名单外引用（含编造编号）必须拒收并触发重提，禁止仅打日志放行。
- 分析输入按批次冻结（指纹），结论可回溯对账。
"""

from __future__ import annotations

import hashlib
from typing import Callable, List, Set

from adgenie.data.domain import RawReview, ValidationResult


def build_whitelist(reviews: List[RawReview]) -> Set[str]:
    """仅 verified 且未过滤评论的编号进入白名单。"""
    return {r.review_id for r in reviews if r.is_verified and not r.filtered_reason}


def validate_evidence(claims: List[dict], whitelist: Set[str]) -> ValidationResult:
    """白名单外引用必须拒收（REJECT_AND_REPROMPT），而不是 WARN。"""
    violations = [c.get("review_id", "") for c in claims
                  if c.get("review_id", "") not in whitelist]
    if violations:
        return ValidationResult(passed=False, violations=violations,
                                action="REJECT_AND_REPROMPT")
    return ValidationResult(passed=True, action="PASS")


def enforce_evidence(
    claim_producer: Callable[[], List[dict]],
    whitelist: Set[str],
    max_reprompt: int = 2,
) -> tuple[List[dict], List[dict], int]:
    """重提循环：最多重试 max_reprompt 次；仍失败则剔除无证据结论。

    返回 (通过结论, 被剔除结论, 尝试次数)。被剔除结论视为「证据不足」，
    绝不保留无证据结论。
    """
    attempts = 0
    for _ in range(max_reprompt + 1):
        attempts += 1
        claims = claim_producer()
        result = validate_evidence(claims, whitelist)
        if result.passed:
            return claims, [], attempts
    # 用尽重试：剔除白名单外结论，保留有证据结论
    claims = claim_producer()
    accepted = [c for c in claims if c.get("review_id", "") in whitelist]
    rejected = [c for c in claims if c.get("review_id", "") not in whitelist]
    return accepted, rejected, attempts


def freeze_batch(reviews: List[RawReview]) -> str:
    """对分析输入批次冻结：生成证据快照指纹（SHA256）。"""
    payload = "|".join(
        f"{r.review_id}:{r.content}" for r in sorted(reviews, key=lambda x: x.review_id)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
