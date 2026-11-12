# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Conector de aristas lineales y condicionales para el ensamblador StateGraph."""

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.core.graph_routes import (
    route_after_evaluation,
    route_after_execute,
    route_after_human_approval,
    route_after_plan,
    route_after_reason,
    route_after_risk_assess,
    route_after_verify,
)
from app.models.state import AgentState


def _connect_reason_edge(
    builder: StateGraph[AgentState],
    topology: Any,
    has_tools: bool,
) -> None:
    """Conecta la arista condicional desde reason."""
    reason_dests = ["conclude"]
    if topology.has_planner:
        reason_dests.append("plan")
    if topology.has_risk_assessment:
        reason_dests.append("risk_assess")
    if has_tools:
        reason_dests.append("execute")

    builder.add_conditional_edges(
        "reason",
        lambda s: route_after_reason(
            s, topology.has_planner, has_tools, topology.has_risk_assessment
        ),
        path_map=list(set(reason_dests)),
    )


def connect_initial_and_planning_edges(
    builder: StateGraph[AgentState],
    topology: Any,
    has_tools: bool,
) -> None:
    """Conecta las aristas iniciales, de reason, plan, risk_assess y human_approval."""
    if topology.has_observer:
        builder.add_edge(START, "observe")
        builder.add_edge("observe", "reason")
    else:
        builder.add_edge(START, "reason")

    _connect_reason_edge(builder, topology, has_tools)

    if topology.has_planner:
        plan_dests = (
            ["conclude", "risk_assess"] if topology.has_risk_assessment else ["conclude", "execute"]
        )
        builder.add_conditional_edges(
            "plan",
            lambda s: route_after_plan(s, topology.has_risk_assessment),
            path_map=list(set(plan_dests)),
        )

    if topology.has_risk_assessment:
        risk_dests = ["execute", "conclude"]
        if topology.has_human_approval:
            risk_dests.append("human_approval")
        builder.add_conditional_edges(
            "risk_assess",
            lambda s: route_after_risk_assess(s, topology.has_human_approval),
            path_map=list(set(risk_dests)),
        )

    if topology.has_human_approval:
        builder.add_conditional_edges(
            "human_approval",
            route_after_human_approval,
            path_map=["execute", "conclude"],
        )


def connect_execution_and_terminal_edges(
    builder: StateGraph[AgentState],
    topology: Any,
) -> None:
    """Conecta las aristas de execute, verify, evaluate, rollback y conclude."""
    exec_dests = ["verify" if topology.has_verifier else "evaluate"]
    if topology.has_rollback:
        exec_dests.append("rollback")
    builder.add_conditional_edges(
        "execute",
        lambda s: route_after_execute(s, topology.has_verifier, topology.has_rollback),
        path_map=exec_dests,
    )

    if topology.has_verifier:
        ver_dests = ["evaluate"] if topology.has_evaluator else ["conclude"]
        if topology.has_rollback:
            ver_dests.append("rollback")
        builder.add_conditional_edges(
            "verify",
            lambda s: route_after_verify(s, topology.has_rollback, topology.has_evaluator),
            path_map=list(set(ver_dests)),
        )

    eval_dests = ["reason", "conclude"]
    if topology.has_rollback:
        eval_dests.append("rollback")
    builder.add_conditional_edges(
        "evaluate",
        lambda s: route_after_evaluation(s, topology.has_rollback),
        path_map=list(set(eval_dests)),
    )

    if topology.has_rollback:
        builder.add_edge("rollback", "conclude")
    builder.add_edge("conclude", END)


def connect_graph_edges(
    builder: StateGraph[AgentState],
    topology: Any,
    has_tools: bool,
) -> None:
    """Orquesta la conexión completa de aristas del grafo."""
    connect_initial_and_planning_edges(builder, topology, has_tools)
    connect_execution_and_terminal_edges(builder, topology)
