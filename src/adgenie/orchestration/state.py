"""LangGraph 图状态定义。

使用 TypedDict 作为 state schema（每个 key 一个 channel，支持并行 fan-out）。
多节点并发写入的 key（node_status / errors）使用合并 reducer 避免冲突。
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, TypedDict


def merge_dict(left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """合并两个 dict（后者覆盖前者），用于多节点并发写同一 key。"""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class GraphState(TypedDict, total=False):
    listing_id: str

    # 数据版本（触发条件）
    profile_version: Optional[str]
    last_used_profile_version: Optional[str]
    copy_version: Optional[str]
    last_scored_copy_version: Optional[str]
    rubric_version: Optional[str]
    last_used_rubric_version: Optional[str]
    knowledge_version: Optional[str]
    last_used_knowledge_version: Optional[str]

    # 输入与中间产物
    copy_text: str
    profile: Optional[dict]
    review_insights: List[dict]
    score_report: Optional[dict]
    competitor_analysis: List[dict]
    strategy: List[dict]

    # 运行状态（多节点并发写 → merge reducer）
    node_status: Annotated[Dict[str, str], merge_dict]
    errors: Annotated[Dict[str, str], merge_dict]
    degradations: Annotated[Dict[str, str], merge_dict]
