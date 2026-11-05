"""DAG 编排集成测试：版本依赖触发、写判分离、故障隔离、端到端。"""

import pytest

from adgenie.config import load_settings
from adgenie.data.factory import DataFactory
from adgenie.data.memory import (
    InMemoryCacheStore,
    InMemoryKnowledgeStore,
    InMemoryMaterialStore,
    InMemoryProfileStore,
    InMemoryReviewStore,
    InMemoryScoreReportStore,
    InMemoryVectorStore,
)
from adgenie.models import DeterministicEmbedder, DeterministicReranker, FakeLLM
from adgenie.orchestration import Container, run_pipeline


def _container(settings, judge=None, writer=None):
    f = DataFactory(seed=42)
    rs = InMemoryReviewStore()
    for r in f.verified_reviews("L-1001", "B000000001", 5):
        rs.insert(r)
    ms = InMemoryMaterialStore()
    vs = InMemoryVectorStore()
    for m in f.materials(12):
        ms.upsert(m)
        vs.upsert(m.material_id, m.embedding)

    writer = writer or FakeLLM(model="qwen-max", temperature=0.7)
    writer.register("广告优化策略专家",
                    '[{"suggestion": "emphasize battery life", "review_id": "R-000"},'
                    ' {"suggestion": "hallucinated", "review_id": "FAKE-1"}]')
    judge = judge or FakeLLM(model="glm-4-plus", temperature=0.0)
    if not judge._script:  # 仅在未预设脚本时注册默认有效响应
        judge.register("广告文案评分裁判",
                       '{"score": 0.85, "items": [{"dimension": "relevance", "score": 0.9, "deductions": []}]}')

    return Container(
        review_store=rs, profile_store=InMemoryProfileStore(),
        score_report_store=InMemoryScoreReportStore(), material_store=ms,
        knowledge_store=InMemoryKnowledgeStore(), vector_store=vs,
        cache=InMemoryCacheStore(), writer=writer, judge=judge,
        embedder=DeterministicEmbedder(), reranker=DeterministicReranker(),
        settings=settings,
    )


def _base_state(**overrides):
    state = {
        "listing_id": "L-1001",
        "profile_version": "v1", "last_used_profile_version": "v1",
        "copy_version": "c1", "last_scored_copy_version": "c1",
        "rubric_version": "v1", "last_used_rubric_version": "v1",
        "knowledge_version": "s1", "last_used_knowledge_version": "s1",
        "copy_text": "battery waterproof fast charging lightweight",
    }
    state.update(overrides)
    return state


def test_write_judge_separation(settings):
    c = _container(settings)
    assert c.writer.model != c.judge.model
    assert c.judge.temperature == 0.0


def test_no_increment_no_agent_wakes(settings):
    c = _container(settings)
    out = run_pipeline(c, _base_state())  # 所有版本均已消费
    status = out.get("node_status", {})
    assert status.get("review_insight") != "ran"
    assert status.get("ad_score") != "ran"
    assert status.get("competitor_analysis") != "ran"


def test_full_pipeline_and_whitelist_rejection(settings):
    c = _container(settings)
    # Phase 1: 仅画像更新 → 评论洞察
    p1 = run_pipeline(c, _base_state(profile_version="v2", last_used_profile_version="v1"))
    assert p1["node_status"]["review_insight"] == "ran"
    # Phase 2: 文案 + 知识库更新 → 评分 + 竞品 + 策略
    p2 = run_pipeline(c, _base_state(
        copy_version="c2", last_scored_copy_version="c1",
        knowledge_version="s2", last_used_knowledge_version="s1",
    ))
    assert p2["node_status"]["ad_score"] == "ran"
    assert p2["node_status"]["competitor_analysis"] == "ran"
    # 编造编号 FAKE-1 被白名单拒收，只保留真实证据 R-000
    ids = [s["review_id"] for s in p2["strategy"]]
    assert "R-000" in ids
    assert "FAKE-1" not in ids
    assert p2.get("score_report") is not None


def test_single_agent_failure_does_not_crash_dag(settings):
    # judge 返回非法 schema → ad_score 失败，但其它节点照常运行
    judge = FakeLLM(model="glm-4-plus", temperature=0.0)
    judge.register("广告文案评分裁判", '{"invalid": true}')
    c = _container(settings, judge=judge)
    out = run_pipeline(c, _base_state(
        profile_version="v2", last_used_profile_version="v1",
        copy_version="c2", last_scored_copy_version="c1",
    ))
    status = out.get("node_status", {})
    assert status.get("ad_score") == "failed"
    assert status.get("review_insight") == "ran"
    assert "ad_score" in out.get("errors", {})
