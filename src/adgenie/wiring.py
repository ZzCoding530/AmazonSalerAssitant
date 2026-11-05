"""依赖组装（Composition Root）。

黄金检验标准：把 ``data_source`` 从 ``seed`` 改为 ``live``，业务代码无需任何修改。
这里仅切换存储/模型实现：
- live：MySQL / Redis / Milvus + OpenAI 兼容 LLM（Qwen 写 / GLM 判）+ BGE-M3 / Cross-Encoder。
- seed：内存存储 + 合成数据 + 确定性替身（演示/自测，不请求外部服务）。

生产实现（mysql_store / redis_store / milvus_store / OpenAICompatibleLLM /
BGEM3Embedder / CrossEncoderReranker）均真实存在；seed 仅替换数据来源与模型实现。
"""

from __future__ import annotations

from adgenie.config import Settings
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
from adgenie.data.milvus_store import MilvusVectorStore
from adgenie.data.mysql_store import MySQLDataStore, build_engine
from adgenie.data.redis_store import RedisCacheStore, build_redis_client
from adgenie.models import (
    BGEM3Embedder,
    CrossEncoderReranker,
    DeterministicEmbedder,
    DeterministicReranker,
    FakeLLM,
    OpenAICompatibleLLM,
)
from adgenie.orchestration.agents import Container


def _seed_data():
    factory = DataFactory(seed=42)
    reviews = []
    reviews += factory.verified_reviews("L-1001", "B000000001", 5)
    reviews += factory.non_verified_reviews("L-1001", "B000000001", 3)
    reviews += factory.shill_reviews("L-1001", "B000000001", 3)
    materials = factory.materials(12)
    return reviews, materials


def _build_seed_container(settings: Settings) -> Container:
    reviews, materials = _seed_data()
    review_store = InMemoryReviewStore()
    for r in reviews:
        review_store.insert(r)
    material_store = InMemoryMaterialStore()
    vector_store = InMemoryVectorStore()
    for m in materials:
        material_store.upsert(m)
        vector_store.upsert(m.material_id, m.embedding)

    writer = FakeLLM(model=settings.llm.writer.model or "qwen-max",
                     temperature=settings.llm.writer.temperature)
    writer.register("广告优化策略专家",
                    '[{"suggestion": "强化电池续航卖点", "review_id": "R-000"},'
                    ' {"suggestion": "补充防水场景证据", "review_id": "R-001"}]')
    judge = FakeLLM(model=settings.llm.judge.model or "glm-4-plus", temperature=0.0)
    judge.register("广告文案评分裁判",
                   '{"score": 0.85, "items": [{"dimension": "relevance", "score": 0.9, "deductions": []}]}')

    return Container(
        review_store=review_store,
        profile_store=InMemoryProfileStore(),
        score_report_store=InMemoryScoreReportStore(),
        material_store=material_store,
        knowledge_store=InMemoryKnowledgeStore(),
        vector_store=vector_store,
        cache=InMemoryCacheStore(),
        writer=writer,
        judge=judge,
        embedder=DeterministicEmbedder(),
        reranker=DeterministicReranker(),
        settings=settings,
    )


def _build_live_container(settings: Settings) -> Container:
    mysql = MySQLDataStore(build_engine(settings.storage.mysql.dsn))
    cache = RedisCacheStore(build_redis_client(settings.storage.redis.url))
    vector = MilvusVectorStore(settings.storage.milvus.uri,
                               settings.storage.milvus.collection)
    writer = OpenAICompatibleLLM(
        base_url=settings.llm.writer.base_url,
        api_key=settings.llm.writer.api_key,
        model=settings.llm.writer.model,
        temperature=settings.llm.writer.temperature,
        timeout=settings.llm.writer.timeout,
    )
    judge = OpenAICompatibleLLM(
        base_url=settings.llm.judge.base_url,
        api_key=settings.llm.judge.api_key,
        model=settings.llm.judge.model,
        temperature=settings.llm.judge.temperature,
        timeout=settings.llm.judge.timeout,
    )
    return Container(
        review_store=mysql,
        profile_store=mysql,
        score_report_store=mysql,
        material_store=mysql,
        knowledge_store=mysql,
        vector_store=vector,
        cache=cache,
        writer=writer,
        judge=judge,
        embedder=BGEM3Embedder(),
        reranker=CrossEncoderReranker(),
        settings=settings,
    )


def build_container(settings: Settings) -> Container:
    """按 data_source 组装依赖；切换 seed/live 无需改业务代码。"""
    if settings.data_source == "live":
        return _build_live_container(settings)
    return _build_seed_container(settings)
