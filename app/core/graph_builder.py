# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Ensamblador agnóstico de grafos LangGraph (GraphBuilder) para jg_agente.

Este módulo construye el flujo StateGraph del motor de ejecución de forma dinámica
inspeccionando exclusivamente el CapabilityRegistry y las herramientas/motores disponibles.
Cumple con el principio de Agnosticismo Radical del Core: la topología se ensambla
exclusivamente por introspección de capacidades sin referencias a dominios ni banderas fijas.
"""

from collections.abc import Callable
from typing import Any, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.graph_edges import connect_graph_edges
from app.core.graph_nodes import (
    default_conclude_node,
    default_evaluate_node,
    default_execute_node,
    default_human_approval_node,
    default_observe_node,
    default_plan_node,
    default_reason_node,
    default_risk_assess_node,
    default_rollback_node,
    default_verify_node,
)
from app.core.graph_topology import GraphTopologyInfo
from app.core.registry import CapabilityRegistry
from app.models.state import AgentState
from app.models.tools import RiskLevel
from app.security.guard import SecurityGuard


def _assemble_topology_lists(
    has_observer: bool,
    has_planner: bool,
    has_risk_assessment: bool,
    has_human_approval: bool,
    has_verifier: bool,
    has_reversible: bool,
) -> tuple[list[str], list[str]]:
    """Genera las listas ordenadas de nodos y nodos condicionales."""
    nodes: list[str] = []
    cond_nodes: list[str] = []
    if has_observer:
        nodes.append("observe")
        cond_nodes.append("observe")
    nodes.append("reason")
    if has_planner:
        nodes.append("plan")
        cond_nodes.append("plan")
    if has_risk_assessment:
        nodes.append("risk_assess")
        cond_nodes.append("risk_assess")
    if has_human_approval:
        nodes.append("human_approval")
        cond_nodes.append("human_approval")
    nodes.append("execute")
    if has_verifier:
        nodes.append("verify")
        cond_nodes.append("verify")
    if has_reversible:
        nodes.append("rollback")
        cond_nodes.append("rollback")
    nodes.extend(["evaluate", "conclude"])
    return nodes, cond_nodes


class GraphBuilder:
    """Ensamblador agnóstico de grafos LangGraph (StateGraph) para jg_agente."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        node_overrides: dict[str, Callable[..., Any]] | None = None,
        security_guard: SecurityGuard | None = None,
        llm: BaseChatModel | None = None,
    ) -> None:
        self.registry = registry
        self.node_overrides = node_overrides or {}
        self.security_guard = security_guard or SecurityGuard()
        self.llm = llm
        self._topology_info: GraphTopologyInfo | None = None

    def get_topology(self) -> GraphTopologyInfo:
        """Calcula e inspecciona los nodos y capacidades que se conectarán en el grafo."""
        has_observer = self.registry.get_observer() is not None or "observe" in self.node_overrides
        has_planner = self.registry.get_planner() is not None or "plan" in self.node_overrides
        has_verifier = self.registry.get_verifier() is not None or "verify" in self.node_overrides

        tools = self.registry.list_tools()
        has_high_risk = (
            any(t.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL) for t in tools)
            or "risk_assess" in self.node_overrides
        )
        has_reversible = any(t.reversible for t in tools) or "rollback" in self.node_overrides

        has_risk_assessment = has_high_risk or has_planner
        has_human_approval = has_high_risk

        nodes, cond_nodes = _assemble_topology_lists(
            has_observer,
            has_planner,
            has_risk_assessment,
            has_human_approval,
            has_verifier,
            has_reversible,
        )

        return GraphTopologyInfo(
            nodes=nodes,
            conditional_nodes=cond_nodes,
            has_observer=has_observer,
            has_planner=has_planner,
            has_risk_assessment=has_risk_assessment,
            has_human_approval=has_human_approval,
            has_verifier=has_verifier,
            has_rollback=has_reversible,
            has_evaluator=True,
        )

    def _register_conditional_nodes(
        self,
        builder: StateGraph[AgentState],
        topology: GraphTopologyInfo,
        checkpoint_degraded: bool,
    ) -> None:
        """Registra los nodos condicionales opcionales."""
        if topology.has_observer:
            h_obs = self.node_overrides.get("observe")

            async def _observe_node(s: AgentState) -> dict[str, Any]:
                return await default_observe_node(s, self.registry)

            builder.add_node("observe", cast(Any, h_obs or _observe_node))

        if topology.has_planner:
            h_plan = self.node_overrides.get("plan")

            async def _plan_node(s: AgentState) -> dict[str, Any]:
                return await default_plan_node(s, self.registry)

            builder.add_node("plan", cast(Any, h_plan or _plan_node))

        if topology.has_risk_assessment:
            h_risk = self.node_overrides.get("risk_assess")

            async def _risk_node(s: AgentState) -> dict[str, Any]:
                if checkpoint_degraded:
                    s = cast(AgentState, {**s, "checkpoint_degraded": True})
                return await default_risk_assess_node(s, self.registry, self.security_guard)

            builder.add_node("risk_assess", cast(Any, h_risk or _risk_node))

        if topology.has_human_approval:
            h_hitl = self.node_overrides.get("human_approval")

            async def _hitl_node(s: AgentState) -> dict[str, Any]:
                return await default_human_approval_node(s, self.registry)

            builder.add_node("human_approval", cast(Any, h_hitl or _hitl_node))

    def _register_execution_nodes(
        self,
        builder: StateGraph[AgentState],
        topology: GraphTopologyInfo,
        checkpoint_degraded: bool,
    ) -> None:
        """Registra los nodos centrales de inferencia y acción física."""
        h_reason = self.node_overrides.get("reason")

        async def _reason_node(s: AgentState) -> dict[str, Any]:
            return await default_reason_node(s, self.registry, llm=self.llm)

        builder.add_node("reason", cast(Any, h_reason or _reason_node))

        h_exec = self.node_overrides.get("execute")

        async def _exec_node(s: AgentState) -> dict[str, Any]:
            if checkpoint_degraded:
                s = cast(AgentState, {**s, "checkpoint_degraded": True})
            return await default_execute_node(s, self.registry, self.security_guard)

        builder.add_node("execute", cast(Any, h_exec or _exec_node))

    def _register_verification_and_terminal_nodes(
        self,
        builder: StateGraph[AgentState],
        topology: GraphTopologyInfo,
    ) -> None:
        """Registra verify, rollback, evaluate y conclude."""
        if topology.has_verifier:
            h_ver = self.node_overrides.get("verify")

            async def _verify_node(s: AgentState) -> dict[str, Any]:
                return await default_verify_node(s, self.registry)

            builder.add_node("verify", cast(Any, h_ver or _verify_node))

        if topology.has_rollback:
            h_rb = self.node_overrides.get("rollback")

            async def _rollback_node(s: AgentState) -> dict[str, Any]:
                return await default_rollback_node(s, self.registry)

            builder.add_node("rollback", cast(Any, h_rb or _rollback_node))

        h_eval = self.node_overrides.get("evaluate")

        async def _evaluate_node(s: AgentState) -> dict[str, Any]:
            return await default_evaluate_node(s, self.registry, llm=self.llm)

        builder.add_node("evaluate", cast(Any, h_eval or _evaluate_node))

        h_conc = self.node_overrides.get("conclude")

        async def _conclude_node(s: AgentState) -> dict[str, Any]:
            return await default_conclude_node(s, self.registry)

        builder.add_node("conclude", cast(Any, h_conc or _conclude_node))

    def _register_action_nodes(
        self,
        builder: StateGraph[AgentState],
        topology: GraphTopologyInfo,
        checkpoint_degraded: bool,
    ) -> None:
        """Registra execute, verify, rollback, reason, evaluate y conclude."""
        self._register_execution_nodes(builder, topology, checkpoint_degraded)
        self._register_verification_and_terminal_nodes(builder, topology)

    def build(
        self,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        interrupt_before: list[str] | None = None,
        interrupt_after: list[str] | None = None,
    ) -> CompiledStateGraph[Any, Any]:
        """Ensambla y compila el StateGraph en un CompiledStateGraph con persistencia y snapshot."""
        topology = self.get_topology()
        self._topology_info = topology

        checkpoint_degraded = bool(getattr(checkpointer, "is_degraded", False))
        builder: StateGraph[AgentState] = StateGraph(AgentState)
        has_tools = len(self.registry.list_tools()) > 0

        self._register_conditional_nodes(builder, topology, checkpoint_degraded)
        self._register_action_nodes(builder, topology, checkpoint_degraded)
        connect_graph_edges(builder, topology, has_tools)

        saver = checkpointer if checkpointer is not None else MemorySaver()
        return builder.compile(
            checkpointer=saver,
            interrupt_before=interrupt_before,
            interrupt_after=interrupt_after,
        )


def build_agent_graph(
    registry: CapabilityRegistry,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    llm: BaseChatModel | None = None,
) -> CompiledStateGraph[Any, Any]:
    """Helper de conveniencia para instanciar y compilar el grafo LangGraph."""
    return GraphBuilder(registry, llm=llm).build(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )
