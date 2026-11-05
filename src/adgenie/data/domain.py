"""领域模型（Pydantic）。

这些对象在采集层、数据访问层、机制层与编排层之间流转，
是「与生产同构的数据访问层」的输入输出契约。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Evidence(BaseModel):
    """一条用户关注点锚定的证据：评论编号 + 原文引用 + 位置。"""

    review_id: str
    quote: str
    position: str = ""


class Concern(BaseModel):
    """一条用户关注点，含命中关键词与证据引用列表。"""

    concern: str
    keywords: List[str] = Field(default_factory=list)
    evidences: List[Evidence] = Field(default_factory=list)


class RawReview(BaseModel):
    """原始评论（落库形态）。"""

    review_id: str
    listing_id: str
    asin: str
    reviewer_id: str
    rating: float
    title: str = ""
    content: str = ""
    is_verified: bool = False
    filtered_reason: str = ""
    raw_html_ref: str = ""
    crawled_at: datetime = Field(default_factory=_utcnow)


class UserProfile(BaseModel):
    """版本化用户画像。"""

    version_id: str
    listing_id: str
    concerns: List[Concern] = Field(default_factory=list)
    evidence_manifest: str = ""
    prev_version_id: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class ScoreReport(BaseModel):
    """评分报告（冻结 manifest，双标尺独立存储）。"""

    report_id: str
    listing_id: str
    copy_version: str
    rubric_version: str
    model_name: str
    temperature: float
    alignment_score: float          # 需求对齐度（代码集合运算）
    persuasion_score: float         # 转化说服力（模型 rubric 逐项）
    detail: List[dict] = Field(default_factory=list)   # 逐条卖点扣分依据
    evidence_snapshot: str = ""     # 证据快照指纹
    created_at: datetime = Field(default_factory=_utcnow)


class Material(BaseModel):
    """竞品素材（进入混合检索与知识库）。"""

    material_id: str
    competitor_id: str
    category: str = ""
    price_band: str = ""
    rating: float = 0.0
    sales_rank: int = 0
    selling_points: List[str] = Field(default_factory=list)
    embedding: List[float] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    archived: bool = False


class KnowledgeEntry(BaseModel):
    """知识库条目（同一卖点变化时更新条目，历史版本保留可回溯）。"""

    entry_id: str
    competitor_id: str
    selling_point_key: str
    selling_point: str
    version: int = 1
    previous_version_id: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    archived: bool = False


class ValidationResult(BaseModel):
    """证据白名单校验结果。"""

    passed: bool
    violations: List[str] = Field(default_factory=list)
    action: str = "PASS"


class CalibrationReport(BaseModel):
    """构造式评分校准结果。"""

    detection_rate: float
    false_alarm_rate: float
    p_value: float
    n_perturbed: int
    n_placebo: int
    rubric_version: str


class VectorHit(BaseModel):
    """向量召回命中项。"""

    material_id: str
    score: float


class RetrievalResult(BaseModel):
    """混合检索最终结果。"""

    material_id: str
    semantic_score: float
    recency_weight: float
    sales_confidence: float
    final_score: float
    archived: bool = False


def asdict(obj: BaseModel) -> dict[str, Any]:
    return obj.model_dump(mode="json")
