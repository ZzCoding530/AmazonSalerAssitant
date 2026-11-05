"""LangGraph 事件驱动 DAG 组装。

- 四类 Agent 独立成节点，按数据版本依赖触发（禁止轮询）。
- 单节点故障只阻断其下游分支（通过 run_node 的故障隔离）。
- 写判分离由 Container 注入的 writer/judge 保证。
"""

from __future__ import annotations

from typing import Dict

from langgraph.graph import END, StateGraph

from adgenie.orchestration.agents import (
    AdScoreAgent,
    AgentNode,
    CompetitorAnalysisAgent,
    Container,
    ReviewInsightAgent,
    StrategyAgent,
    run_node,
)
from adgenie.orchestration.state import GraphState
from adgenie.orchestration.triggers import (
    ad_score_ready,
    competitor_analysis_ready,
    review_insight_ready,
)

_NODE_NAMES = ["review_insight", "ad_score", "competitor_analysis", "strategy_gen"]


def build_agents(container: Container) -> Dict[str, AgentNode]:
    return {
        "review_insight": ReviewInsightAgent(container),
        "ad_score": AdScoreAgent(container),
        "competitor_analysis": CompetitorAnalysisAgent(container),
        "strategy_gen": StrategyAgent(container),
    }


def _fanout(state: dict) -> list[str]:
    """路由：仅唤醒有增量输入的节点。"""
    routes: list[str] = []
    if review_insight_ready(state):
        routes.append("review_insight")
    if ad_score_ready(state):
        routes.append("ad_score")
    if competitor_analysis_ready(state):
        routes.append("competitor_analysis")
    if not routes:
        routes.append("strategy_gen")  # 无增量输入：直接到策略节点（其内部会因依赖未就绪而跳过）
    return routes


def build_graph(agents: Dict[str, AgentNode]):
    graph = StateGraph(GraphState)

    graph.add_node("router", lambda s: {})
    for name, agent in agents.items():
        graph.add_node(name, lambda state, a=agent: run_node(a, state))

    graph.set_entry_point("router")
    graph.add_conditional_edges("router", _fanout,
                                path_map={n: n for n in _NODE_NAMES})
    graph.add_edge("review_insight", "strategy_gen")
    graph.add_edge("ad_score", "strategy_gen")
    graph.add_edge("competitor_analysis", "strategy_gen")
    graph.add_edge("strategy_gen", END)
    return graph.compile()


def run_pipeline(container: Container, initial_state: dict) -> dict:
    """端到端执行 DAG。"""
    agents = build_agents(container)
    app = build_graph(agents)
    return app.invoke(initial_state)
