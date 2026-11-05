"""机制四：时效感知混合检索（三段式）。

1. 元数据粗筛（类目/价格带/评分段/榜单排名）——禁止跳过。
2. BGE-M3 向量召回。
3. Cross-Encoder 精排 + 语义相关度 × 时效衰减 × 销量置信度融合。
过期素材自动降权并标记归档。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from adgenie.config import RetrievalConfig
from adgenie.data.domain import Material, RetrievalResult
from adgenie.data.ports import MaterialStore, VectorStore
from adgenie.models import Embedder, Reranker


def _age_days(updated_at: Optional[datetime]) -> float:
    if updated_at is None:
        return 0.0
    now = datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - updated_at).total_seconds() / 86400.0)


def _recency_weight(age_days: float, half_life_days: int) -> float:
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def _sales_confidence(sales_rank: int) -> float:
    return 1.0 / (1.0 + max(0, sales_rank) / 100.0)


def _minmax(scores: List[float]) -> List[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [1.0 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def hybrid_search(
    query: str,
    *,
    category: Optional[str],
    price_band: Optional[str],
    rating_min: Optional[float],
    rating_max: Optional[float],
    sales_rank_max: Optional[int],
    material_store: MaterialStore,
    vector_store: VectorStore,
    embedder: Embedder,
    reranker: Reranker,
    config: RetrievalConfig,
) -> List[RetrievalResult]:
    """三段式混合检索。粗筛为空时直接返回空，禁止跳过粗筛全库向量检索。"""
    # 第一段：元数据粗筛
    candidates = material_store.coarse_filter(
        category, price_band, rating_min, rating_max, sales_rank_max)
    if not candidates:
        return []
    candidate_ids = [m.material_id for m in candidates]
    by_id = {m.material_id: m for m in candidates}

    # 第二段：BGE-M3 向量召回（仅在候选集合内）
    query_vec = embedder.embed(query)
    hits = vector_store.search(query_vec, candidate_ids, config.top_k_recall)
    if not hits:
        return []

    # 第三段：Cross-Encoder 精排 + 融合
    docs: List[str] = []
    for h in hits:
        m = by_id.get(h.material_id)
        docs.append(" ".join(m.selling_points) if m else "")
    rerank_scores = _minmax(reranker.rerank(query, docs))

    results: List[RetrievalResult] = []
    for h, semantic in zip(hits, rerank_scores):
        material = by_id.get(h.material_id)
        if material is None:
            continue
        age = _age_days(material.updated_at)
        recency = _recency_weight(age, config.recency_half_life_days)
        sales = _sales_confidence(material.sales_rank)
        w = config.weights
        final = w.semantic * semantic + w.recency_decay * recency + w.sales_confidence * sales
        results.append(RetrievalResult(
            material_id=material.material_id,
            semantic_score=round(semantic, 4),
            recency_weight=round(recency, 4),
            sales_confidence=round(sales, 4),
            final_score=round(final, 4),
            archived=bool(material.archived or age > config.recency_half_life_days * 4),
        ))

    results.sort(key=lambda r: r.final_score, reverse=True)
    return results[:config.top_k_final]
