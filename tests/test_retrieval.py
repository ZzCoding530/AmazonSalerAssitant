"""机制四：时效感知混合检索 单元测试。"""

from datetime import datetime, timedelta, timezone

from adgenie.data.domain import Material
from adgenie.data.memory import InMemoryMaterialStore, InMemoryVectorStore
from adgenie.mechanisms.retrieval import hybrid_search
from adgenie.models import DeterministicEmbedder, DeterministicReranker


def _material(mid, category, price_band, rating, rank, age_days, selling):
    now = datetime.now(timezone.utc)
    updated = now - timedelta(days=age_days)
    return Material(material_id=mid, competitor_id="C", category=category,
                    price_band=price_band, rating=rating, sales_rank=rank,
                    selling_points=selling,
                    embedding=DeterministicEmbedder().embed(" ".join(selling)),
                    updated_at=updated, created_at=updated)


def _setup(settings):
    embedder = DeterministicEmbedder()
    ms = InMemoryMaterialStore()
    vs = InMemoryVectorStore()
    materials = [
        _material("M1", "electronics", "mid", 4.5, 10, 10, ["battery life", "fast charging"]),
        _material("M2", "electronics", "mid", 4.2, 50, 5, ["battery life"]),
        _material("M3", "home", "high", 4.8, 3, 20, ["noise cancellation"]),
        _material("M4", "electronics", "mid", 4.6, 5, 400, ["battery life", "waterproof"]),
    ]
    for m in materials:
        ms.upsert(m)
        vs.upsert(m.material_id, m.embedding)
    return ms, vs, embedder


def test_coarse_filter_excludes_other_category(settings):
    ms, vs, embedder = _setup(settings)
    results = hybrid_search(
        "battery life", category="electronics", price_band=None,
        rating_min=None, rating_max=None, sales_rank_max=None,
        material_store=ms, vector_store=vs, embedder=embedder,
        reranker=DeterministicReranker(embedder), config=settings.retrieval)
    ids = {r.material_id for r in results}
    assert "M3" not in ids  # home 类目被粗筛排除
    assert ids <= {"M1", "M2", "M4"}


def test_empty_candidates_returns_empty(settings):
    ms, vs, embedder = _setup(settings)
    results = hybrid_search(
        "x", category="nonexistent", price_band=None,
        rating_min=None, rating_max=None, sales_rank_max=None,
        material_store=ms, vector_store=vs, embedder=embedder,
        reranker=DeterministicReranker(embedder), config=settings.retrieval)
    assert results == []


def test_expired_material_downscores_and_archived(settings):
    ms, vs, embedder = _setup(settings)
    results = hybrid_search(
        "battery life", category="electronics", price_band=None,
        rating_min=None, rating_max=None, sales_rank_max=None,
        material_store=ms, vector_store=vs, embedder=embedder,
        reranker=DeterministicReranker(embedder), config=settings.retrieval)
    by_id = {r.material_id: r for r in results}
    # 过期素材 M4 被标记归档
    assert by_id["M4"].archived is True
    # 时效衰减：M4 的 recency 权重低于近期素材 M1
    assert by_id["M4"].recency_weight < by_id["M1"].recency_weight


def test_result_capped_by_top_k_final(settings):
    ms, vs, embedder = _setup(settings)
    results = hybrid_search(
        "battery", category=None, price_band=None,
        rating_min=None, rating_max=None, sales_rank_max=None,
        material_store=ms, vector_store=vs, embedder=embedder,
        reranker=DeterministicReranker(embedder), config=settings.retrieval)
    assert len(results) <= settings.retrieval.top_k_final
