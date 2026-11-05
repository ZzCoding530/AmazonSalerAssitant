"""机制五：知识库自更新闭环。

- 增量入库：竞品素材卖点进入知识库。
- 同一竞品卖点变化时更新条目（版本+1）而非重复堆积，历史版本保留可回溯。
- 过时素材检测与归档。
"""

from __future__ import annotations

from typing import List

from adgenie.config import KnowledgeBaseConfig
from adgenie.data.domain import Material
from adgenie.data.ports import KnowledgeStore
from adgenie.mechanisms.scoring import extract_keywords


def selling_point_key(selling_point: str) -> str:
    """以卖点的核心维度（首关键词）作为稳定 key，文本变化时同 key 升版本。"""
    tokens = sorted(extract_keywords(selling_point))
    return tokens[0] if tokens else f"sp:{abs(hash(selling_point))}"


class KnowledgeBase:
    def __init__(self, store: KnowledgeStore, config: KnowledgeBaseConfig):
        self._store = store
        self._config = config

    def update_from_materials(self, materials: List[Material]) -> int:
        """增量入库，返回更新/新增的条目数。"""
        count = 0
        for m in materials:
            for sp in m.selling_points:
                if not sp:
                    continue
                self._store.upsert_selling_point(
                    competitor_id=m.competitor_id,
                    selling_point_key=selling_point_key(sp),
                    selling_point=sp,
                )
                count += 1
        return count

    def archive_outdated(self) -> int:
        return self._store.archive_outdated(self._config.recency_threshold_days)

    def list_active(self):
        return self._store.list_active()

    def history(self, selling_point_key: str):
        return self._store.history(selling_point_key)
