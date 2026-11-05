"""数据访问层抽象接口（Ports）。

依据《开发规范》第 2.2 节与第 4 节：
- 存储分工固定：MySQL（原始+业务）/ Redis（缓存）/ Milvus（向量）。
- 所有外部存储必须通过接口抽象注入；生产实现必须真实存在（见
  ``mysql_store`` / ``redis_store`` / ``milvus_store``），测试通过
  ``memory`` 中的内存实现替换，但内存实现仅用于测试。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from adgenie.data.domain import (
    KnowledgeEntry,
    Material,
    RawReview,
    ScoreReport,
    UserProfile,
    VectorHit,
)


class ReviewStore(ABC):
    @abstractmethod
    def insert(self, review: RawReview) -> bool:
        """入库；若唯一键已存在（重复评论）返回 False。"""

    @abstractmethod
    def exists(self, listing_id: str, review_id: str) -> bool:
        """判断评论是否已存在（增量去重）。"""

    @abstractmethod
    def get_by_listing(self, listing_id: str) -> List[RawReview]:
        """返回某 Listing 的全部原始评论（含被过滤记录，便于审计）。"""

    @abstractmethod
    def get_verified(self, listing_id: str) -> List[RawReview]:
        """返回仅 verified purchase 且未被过滤的评论。"""

    @abstractmethod
    def mark_filtered(self, review_id: str, reason: str) -> None:
        """标记过滤原因（未购/水军/重复），记录仍需保留可审计。"""


class ProfileStore(ABC):
    @abstractmethod
    def save_version(self, profile: UserProfile) -> str:
        """保存画像版本，返回 version_id。"""

    @abstractmethod
    def get_latest(self, listing_id: str) -> Optional[UserProfile]: ...

    @abstractmethod
    def get(self, version_id: str) -> Optional[UserProfile]: ...


class ScoreReportStore(ABC):
    @abstractmethod
    def save(self, report: ScoreReport) -> str: ...

    @abstractmethod
    def get(self, report_id: str) -> Optional[ScoreReport]: ...

    @abstractmethod
    def list_for_listing(self, listing_id: str) -> List[ScoreReport]: ...


class MaterialStore(ABC):
    @abstractmethod
    def upsert(self, material: Material) -> None: ...

    @abstractmethod
    def get(self, material_id: str) -> Optional[Material]: ...

    @abstractmethod
    def list_all(self) -> List[Material]: ...

    @abstractmethod
    def coarse_filter(self, category: Optional[str], price_band: Optional[str],
                      rating_min: Optional[float], rating_max: Optional[float],
                      sales_rank_max: Optional[int]) -> List[Material]:
        """元数据粗筛（类目/价格带/评分段/榜单排名）。"""


class KnowledgeStore(ABC):
    @abstractmethod
    def upsert_selling_point(self, competitor_id: str, selling_point_key: str,
                             selling_point: str) -> KnowledgeEntry:
        """同一卖点变化时更新条目（版本+1）而非重复堆积。"""

    @abstractmethod
    def list_active(self) -> List[KnowledgeEntry]: ...

    @abstractmethod
    def history(self, selling_point_key: str) -> List[KnowledgeEntry]: ...

    @abstractmethod
    def archive_outdated(self, older_than_days: int) -> int:
        """归档过期素材，返回归档条数。"""


class CacheStore(ABC):
    @abstractmethod
    def bloom_add(self, key: str, item: str) -> bool: ...

    @abstractmethod
    def bloom_contains(self, key: str, item: str) -> bool: ...

    @abstractmethod
    def rate_increment(self, key: str, window_seconds: int) -> int: ...

    @abstractmethod
    def get(self, key: str) -> Optional[str]: ...

    @abstractmethod
    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, material_id: str, vector: List[float]) -> None: ...

    @abstractmethod
    def search(self, query_vector: List[float], candidate_ids: List[str],
               top_k: int) -> List[VectorHit]:
        """在候选集合内做向量召回（禁止跳过粗筛直接全库检索）。"""
