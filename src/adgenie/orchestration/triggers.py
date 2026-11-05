"""版本依赖触发谓词（禁止轮询）。

每个 Agent 订阅「数据版本」而非「时间」；无增量输入时节点不唤醒。
"""

from __future__ import annotations


def review_insight_ready(state: dict) -> bool:
    """评论洞察：画像版本 vₙ 更新（有新评论入库）。"""
    return state.get("profile_version") != state.get("last_used_profile_version")


def ad_score_ready(state: dict) -> bool:
    """广告评分：待评文案变更 或 rubric 版本升级。"""
    copy_changed = state.get("copy_version") != state.get("last_scored_copy_version")
    rubric_changed = state.get("rubric_version") != state.get("last_used_rubric_version")
    return copy_changed or rubric_changed


def competitor_analysis_ready(state: dict) -> bool:
    """竞品分析：知识库快照 sₖ 更新。"""
    return state.get("knowledge_version") != state.get("last_used_knowledge_version")


def strategy_gen_ready(state: dict) -> bool:
    """策略生成：评分报告 vₘ + 洞察结论 同时就绪。"""
    return bool(state.get("score_report")) and bool(state.get("review_insights"))
