"""四类 Agent 节点实现 + 通用节点包装器。

每个 Agent 节点四件套：validate_input / validate_output / execute / on_failure。
- 评论洞察 / 广告评分 / 竞品分析 / 策略生成 独立成节点。
- 写判分离：StrategyAgent 用 writer（Qwen/DeepSeek），AdScoreAgent 用 judge（GLM，温度 0）。
- 单 Agent 故障只影响其下游分支，不崩溃整个 DAG。
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List

from adgenie.config import Settings
from adgenie.data.domain import (
    Concern,
    ScoreReport,
    UserProfile,
)
from adgenie.data.ports import (
    CacheStore,
    KnowledgeStore,
    MaterialStore,
    ProfileStore,
    ReviewStore,
    ScoreReportStore,
    VectorStore,
)
from adgenie.mechanisms.evidence import (
    build_whitelist,
    enforce_evidence,
    freeze_batch,
    validate_evidence,
)
from adgenie.mechanisms.knowledge_base import KnowledgeBase
from adgenie.mechanisms.manifest import compute_evidence_fingerprint
from adgenie.mechanisms.retrieval import hybrid_search
from adgenie.mechanisms.scoring import compute_alignment, extract_keywords, score_persuasion
from adgenie.models import Embedder, LLMClient, Reranker


@dataclass
class Container:
    """注入全部外部依赖（存储 / 模型 / 配置）。"""
    review_store: ReviewStore
    profile_store: ProfileStore
    score_report_store: ScoreReportStore
    material_store: MaterialStore
    knowledge_store: KnowledgeStore
    vector_store: VectorStore
    cache: CacheStore
    writer: LLMClient
    judge: LLMClient
    embedder: Embedder
    reranker: Reranker
    settings: Settings


class AgentNode(ABC):
    name: str = "agent"

    @abstractmethod
    def validate_input(self, state: dict) -> None: ...

    @abstractmethod
    def validate_output(self, result: dict) -> None: ...

    @abstractmethod
    def execute(self, state: dict) -> dict:
        """返回局部 state 更新。"""

    @abstractmethod
    def on_failure(self, state: dict, err: Exception) -> str:
        """返回显式声明的降级策略名。"""


def _failure_update(agent: AgentNode, state: dict, msg: str) -> dict:
    degradation = agent.on_failure(state, Exception(msg))
    return {
        "node_status": {agent.name: "failed"},
        "errors": {agent.name: msg},
        "degradations": {agent.name: degradation},
    }


def run_node(agent: AgentNode, state: dict, retry_max: int = 2) -> dict:
    """通用节点包装：输入校验 → 执行（重试）→ 输出校验 → 故障隔离。"""
    try:
        agent.validate_input(state)
    except Exception as exc:  # 输入校验失败即隔离，不崩溃 DAG
        return _failure_update(agent, state, f"input validation: {exc}")

    last_err: Exception | None = None
    for _ in range(retry_max + 1):
        try:
            result = agent.execute(state)
            agent.validate_output(result)
            result.setdefault("node_status", {})
            result["node_status"].setdefault(agent.name, "ran")
            return result
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    return _failure_update(agent, state, str(last_err))


class ReviewInsightAgent(AgentNode):
    name = "review_insight"

    def __init__(self, container: Container):
        self.c = container

    def validate_input(self, state: dict) -> None:
        if not state.get("listing_id"):
            raise ValueError("listing_id required")

    def validate_output(self, result: dict) -> None:
        if "review_insights" not in result:
            raise ValueError("review_insights missing")
        if not isinstance(result["review_insights"], list):
            raise ValueError("review_insights must be a list")

    def execute(self, state: dict) -> dict:
        listing_id = state["listing_id"]
        reviews = self.c.review_store.get_verified(listing_id)
        profile_version = state.get("profile_version") or f"{listing_id}:v0"

        concerns = self._build_concerns(reviews)
        whitelist = build_whitelist(reviews)
        # 证据锚定校验：评论洞察产出的引用必须命中白名单（真实编号，理应通过）
        validation = validate_evidence(
            [{"review_id": e["review_id"]}
             for c in concerns for e in c["evidences"]], whitelist)
        if not validation.passed:
            raise ValueError(f"evidence validation failed: {validation.violations}")

        profile = UserProfile(
            version_id=profile_version,
            listing_id=listing_id,
            concerns=[Concern(**c) for c in concerns],
            evidence_manifest=freeze_batch(reviews),
        )
        self.c.profile_store.save_version(profile)

        return {
            "review_insights": concerns,
            "profile": profile.model_dump(mode="json"),
            "last_used_profile_version": profile_version,
        }

    @staticmethod
    def _build_concerns(reviews) -> List[dict]:
        groups: dict[str, dict] = {}
        for r in reviews:
            for kw in extract_keywords(r.content):
                g = groups.setdefault(kw, {"concern": kw, "keywords": [kw], "evidences": []})
                g["evidences"].append({
                    "review_id": r.review_id,
                    "quote": r.content[:120],
                    "position": "",
                })
        return list(groups.values())

    def on_failure(self, state: dict, err: Exception) -> str:
        return "skip_downstream"


class AdScoreAgent(AgentNode):
    name = "ad_score"

    def __init__(self, container: Container):
        self.c = container

    def validate_input(self, state: dict) -> None:
        if not state.get("copy_text"):
            raise ValueError("copy_text required")

    def validate_output(self, result: dict) -> None:
        if "score_report" not in result:
            raise ValueError("score_report missing")

    def execute(self, state: dict) -> dict:
        copy_text = state["copy_text"]
        listing_id = state["listing_id"]
        rubric_version = state.get("rubric_version") or self.c.settings.scoring.rubric_version

        # 需求对齐度的输入来自「最新画像版本」（持久化），而非同次运行的瞬时状态，
        # 以契合版本依赖语义：广告评分订阅待评文案/rubric 版本，读取最新画像。
        profile = self.c.profile_store.get_latest(listing_id)
        if profile is not None:
            concerns = [c.model_dump() for c in profile.concerns]
        else:
            concerns = state.get("review_insights") or []
        concern_keywords = [kw for c in concerns for kw in c.get("keywords", [])]
        evidences = [e for c in concerns for e in c.get("evidences", [])]

        # 双标尺之一：需求对齐度（代码集合运算）
        alignment = compute_alignment(copy_text, concern_keywords)
        # 双标尺之二：转化说服力（Judge rubric，温度 0）
        persuasion = score_persuasion(self.c.judge, rubric_version, copy_text, evidences)

        # 冻结 manifest：固化 rubric 版本/模型/温度/证据指纹
        snapshot = compute_evidence_fingerprint([e["review_id"] for e in evidences])
        detail = [
            {"type": "alignment", "score": alignment.score,
             "matched": alignment.matched, "missing": alignment.missing},
        ] + persuasion.items

        report = ScoreReport(
            report_id=f"RPT-{uuid.uuid4().hex[:12]}",
            listing_id=listing_id,
            copy_version=state.get("copy_version") or "v0",
            rubric_version=rubric_version,
            model_name=self.c.judge.model,
            temperature=self.c.judge.temperature,
            alignment_score=alignment.score,
            persuasion_score=persuasion.score,
            detail=detail,
            evidence_snapshot=snapshot,
        )
        self.c.score_report_store.save(report)

        return {
            "score_report": report.model_dump(mode="json"),
            "last_scored_copy_version": state.get("copy_version"),
            "last_used_rubric_version": rubric_version,
        }

    def on_failure(self, state: dict, err: Exception) -> str:
        return "skip_downstream"


class CompetitorAnalysisAgent(AgentNode):
    name = "competitor_analysis"

    def __init__(self, container: Container):
        self.c = container
        self._kb = KnowledgeBase(container.knowledge_store, container.settings.knowledge_base)

    def validate_input(self, state: dict) -> None:
        if not state.get("listing_id"):
            raise ValueError("listing_id required")

    def validate_output(self, result: dict) -> None:
        if "competitor_analysis" not in result:
            raise ValueError("competitor_analysis missing")

    def execute(self, state: dict) -> dict:
        concerns = state.get("review_insights") or []
        query = " ".join(kw for c in concerns for kw in c.get("keywords", [])) or "electronics"
        cfg = self.c.settings.retrieval

        # 三段式混合检索
        hits = hybrid_search(
            query,
            category=None, price_band=None,
            rating_min=None, rating_max=None, sales_rank_max=None,
            material_store=self.c.material_store,
            vector_store=self.c.vector_store,
            embedder=self.c.embedder,
            reranker=self.c.reranker,
            config=cfg,
        )

        analysis: List[dict] = []
        materials = [m for m in self.c.material_store.list_all()]
        for h in hits:
            m = next((m for m in materials if m.material_id == h.material_id), None)
            analysis.append({
                "material_id": h.material_id,
                "final_score": h.final_score,
                "selling_points": m.selling_points if m else [],
                "archived": h.archived,
            })

        # 知识库自更新闭环：增量入库 + 过期归档
        self._kb.update_from_materials(materials)
        self._kb.archive_outdated()

        return {
            "competitor_analysis": analysis,
            "last_used_knowledge_version": state.get("knowledge_version"),
        }

    def on_failure(self, state: dict, err: Exception) -> str:
        return "skip_downstream"


class StrategyAgent(AgentNode):
    name = "strategy_gen"

    def __init__(self, container: Container):
        self.c = container

    def validate_input(self, state: dict) -> None:
        if not state.get("listing_id"):
            raise ValueError("listing_id required")

    def validate_output(self, result: dict) -> None:
        if "strategy" not in result:
            raise ValueError("strategy missing")

    def execute(self, state: dict) -> dict:
        listing_id = state["listing_id"]
        # 依赖评分报告（本运行产出或已持久化）+ 最新洞察结论（画像版本）
        profile = self.c.profile_store.get_latest(listing_id)
        score_report = state.get("score_report")
        if score_report is None:
            reports = self.c.score_report_store.list_for_listing(listing_id)
            score_report = reports[0].model_dump(mode="json") if reports else None

        if profile is None or score_report is None:
            return {
                "strategy": [],
                "node_status": {self.name: "skipped: deps not ready"},
            }

        concerns = [c.model_dump() for c in profile.concerns]
        whitelist = {e["review_id"] for c in concerns for e in c.get("evidences", [])}
        prompt = self._build_prompt(score_report, state.get("competitor_analysis") or [])

        def produce() -> List[dict]:
            raw = self.c.writer.complete(prompt)
            return self._parse_strategy(raw)

        accepted, _rejected, _attempts = enforce_evidence(
            produce, whitelist, self.c.settings.evidence.max_reprompt)
        return {"strategy": accepted}

    @staticmethod
    def _build_prompt(report: dict, competitors: list) -> str:
        return (
            "你是广告优化策略专家。请基于下面的评分报告与竞品分析，"
            "生成 3 条优化建议，每条必须引用具体评论编号（review_id）作为证据。\n"
            "只输出 JSON 数组，格式：[{\"suggestion\": \"...\", \"review_id\": \"R-001\"}]\n"
            f"评分报告：{json.dumps(report, ensure_ascii=False)}\n"
            f"竞品分析：{json.dumps(competitors, ensure_ascii=False)}\n"
        )

    @staticmethod
    def _parse_strategy(raw: str) -> List[dict]:
        text = raw.strip()
        fence = text.find("[")
        tail = text.rfind("]")
        if fence != -1 and tail > fence:
            text = text[fence:tail + 1]
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("strategy output must be a list")
        return data

    def on_failure(self, state: dict, err: Exception) -> str:
        return "evidence_insufficient"
