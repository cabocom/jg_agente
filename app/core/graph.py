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
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalStatus,
    GoalStatus,
    IntentModel,
    PolicyDecision,
    StepStatus,
    VerificationStatus,
)
from app.models.tools import RiskLevel
from app.security.guard import SecurityGuard


class GraphTopologyInfo(BaseModel):
    """Metadatos de la topología del grafo ensamblado dinámicamente."""

    nodes: list[str] = Field(
        default_factory=list,
        description="Identificadores de todos los nodos agregados al grafo",
    )
    conditional_nodes: list[str] = Field(
        default_factory=list,
        description="Nodos condicionales incluidos basados en capacidades registradas",
    )
    has_observer: bool = Field(default=False, description="Indica si se conectó el nodo observe")
    has_planner: bool = Field(default=False, description="Indica si se conectó el nodo plan")
    has_risk_assessment: bool = Field(
        default=False, description="Indica si se conectó el nodo risk_assess"
    )
    has_human_approval: bool = Field(
        default=False, description="Indica si se conectó el nodo human_approval"
    )
    has_verifier: bool = Field(default=False, description="Indica si se conectó el nodo verify")
    has_rollback: bool = Field(default=False, description="Indica si se conectó el nodo rollback")
    has_evaluator: bool = Field(default=True, description="Indica si se conectó el nodo evaluate")


# ==========================================================
# 1. Nodos Canónicos y Auxiliares por Defecto (Agnósticos)
# ==========================================================


async def default_observe_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de observación: captura el estado del entorno delegando en observe_node."""
    from app.nodes.observe import observe_node

    return await observe_node(state, registry=registry)


async def default_reason_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Nodo de razonamiento cognitivo: delega en el nodo reason con modelo LLM configurable."""
    from app.nodes.reason import reason_node

    return await reason_node(state, registry, llm=llm)


async def default_plan_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de planificación: genera una secuencia de pasos estructurados delegando en plan_node."""
    from app.nodes.plan import plan_node

    return await plan_node(state, registry=registry)


async def default_risk_assess_node(
    state: AgentState,
    registry: CapabilityRegistry,
    security_guard: SecurityGuard,
) -> dict[str, Any]:
    """Nodo de evaluación de riesgo de operaciones delegando en risk_assess_node."""
    from app.nodes.risk_assess import risk_assess_node

    return await risk_assess_node(state, registry=registry, security_guard=security_guard)


async def default_human_approval_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de gestión de aprobación humana (HITL) delegando en human_approval_node."""
    from app.nodes.human_approval import human_approval_node

    return await human_approval_node(state, registry=registry)


async def default_execute_node(
    state: AgentState,
    registry: CapabilityRegistry,
    security_guard: SecurityGuard,
) -> dict[str, Any]:
    """Nodo de ejecución de acciones: delega en execute_node bajo sandbox seguro."""
    from app.nodes.execute import execute_node

    return await execute_node(state, registry, security_guard=security_guard)


async def default_verify_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de verificación: delega en verify_node."""
    from app.nodes.verify import verify_node

    return await verify_node(state, registry=registry)


async def default_rollback_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de compensación (Rollback): delega en rollback_node."""
    from app.nodes.rollback import rollback_node

    return await rollback_node(state, registry=registry)


async def default_evaluate_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Nodo de evaluación semántica: delega en evaluate_node con capability-awareness."""
    from app.nodes.evaluate import evaluate_node

    return await evaluate_node(state, registry=registry, llm=llm)


async def default_conclude_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de conclusión: delega en conclude_node para consolidar la salida AgentOutput."""
    from app.nodes.conclude import conclude_node

    return await conclude_node(state, registry=registry)


# ==========================================================
# 2. Enrutadores Condicionales Agnósticos
# ==========================================================


def route_after_reason(
    state: AgentState,
    has_planner: bool,
    has_tools: bool,
    has_risk_assessment: bool = False,
) -> str:
    """Enruta desde 'reason' según la intención detectada y las capacidades disponibles."""
    intent = state.get("intent")
    action_type = ""
    if isinstance(intent, IntentModel):
        action_type = intent.action_type
    elif isinstance(intent, dict):
        action_type = intent.get("action_type", "")

    if action_type in ("conclude", "respond"):
        return "conclude"
    if has_planner:
        return "plan"
    if has_risk_assessment:
        return "risk_assess"
    if has_tools:
        return "execute"
    return "conclude"


def route_after_plan(state: AgentState, has_risk_assessment: bool) -> str:
    """Enruta desde 'plan' hacia evaluación de riesgo si existe, ejecución o conclude si falló."""
    plan = state.get("plan")
    has_steps = bool(plan and getattr(plan, "steps", None))
    has_fatal_error = any(getattr(e, "fatal", False) for e in (state.get("errors") or []))
    is_failed = (
        (not has_steps)
        or has_fatal_error
        or state.get("status") in (AgentExecutionStatus.FAILED, AgentExecutionStatus.FAILED.value)
    )

    if is_failed:
        return "conclude"

    if has_risk_assessment:
        return "risk_assess"
    return "execute"


def route_after_risk_assess(state: AgentState, has_human_approval: bool) -> str:
    """Enruta desde 'risk_assess' evaluando la política de seguridad."""
    risk_info = state.get("risk_assessment") or {}
    decision = (
        risk_info.get("decision")
        if isinstance(risk_info, dict)
        else getattr(risk_info, "decision", None)
    )

    if decision == PolicyDecision.DENY or decision == PolicyDecision.DENY.value:
        return "conclude"

    approval = state.get("approval")
    approval_status = (
        getattr(approval, "status", None)
        if approval
        else (approval.get("status") if isinstance(approval, dict) else None)
    )

    if (
        decision
        in (PolicyDecision.REQUIRE_HUMAN_APPROVAL, PolicyDecision.REQUIRE_HUMAN_APPROVAL.value)
        or approval_status == ApprovalStatus.PENDING
        or state.get("requires_approval") is True
        or state.get("human_intervention_required") is True
    ):
        if has_human_approval:
            return "human_approval"
        return "conclude"

    return "execute"


def route_after_human_approval(state: AgentState) -> str:
    """Enruta desde 'human_approval' tras evaluar el resultado de la autorización."""
    approval = state.get("approval")
    approval_status = (
        getattr(approval, "status", None)
        if approval
        else (approval.get("status") if isinstance(approval, dict) else None)
    )

    if approval_status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.AUTO_APPROVED.value,
    ):
        return "execute"
    return "conclude"


def route_after_execute(
    state: AgentState,
    has_verifier: bool,
    has_rollback: bool = False,
) -> str:
    """Enruta tras 'execute' hacia compensación, verificación o evaluación semántica.

    Si un paso crítico falló y existen pasos reversibles completados (requires_rollback),
    la compensación es obligatoria y se ejecuta antes de cualquier otra transición.
    """
    if has_rollback and state.get("requires_rollback"):
        records = state.get("execution_records") or []
        if any(
            r.status == StepStatus.COMPLETED and r.rollback_context is not None for r in records
        ):
            return "rollback"
    if has_verifier:
        return "verify"
    return "evaluate"


def route_after_verify(
    state: AgentState,
    has_rollback: bool,
    has_evaluator: bool = True,
) -> str:
    """Enruta tras 'verify' evaluando si la comprobación fue exitosa o requiere compensación."""
    v_results = state.get("verification_results") or []
    has_failure = any(
        v.get("status") in (VerificationStatus.FAIL.value, VerificationStatus.DEGRADED.value)
        if isinstance(v, dict)
        else getattr(v, "status", None) in (VerificationStatus.FAIL, VerificationStatus.DEGRADED)
        for v in v_results
    )

    if has_failure and has_rollback:
        records = state.get("execution_records") or []
        has_reversible = any(
            r.status == StepStatus.COMPLETED and r.rollback_context is not None for r in records
        )
        if has_reversible:
            return "rollback"

    return "evaluate"


def route_after_evaluation(state: AgentState, has_rollback: bool = False) -> str:
    """Enruta tras 'evaluate' aplicando guardarraíles deterministas de iteración y estado del objetivo."""
    # 1. Guardarraíl de compensación si la evaluación o verificación detectó requerimiento explícito
    if state.get("requires_rollback") and has_rollback:
        return "rollback"

    # 2. Guardarraíl determinista de límite de iteraciones (previene bucles infinitos)
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 3)
    if iteration >= max_iterations:
        return "conclude"

    # 3. Inspección del último EvaluationRecord
    eval_records = state.get("evaluation_records") or []
    if not eval_records:
        return "conclude"

    last_eval = eval_records[-1]
    goal_status = getattr(last_eval, "goal_status", None)
    if isinstance(goal_status, GoalStatus):
        status_val = goal_status.value
    else:
        status_val = str(goal_status or "").lower().strip()

    # Si faltan capacidades, o ya está satisfecho o falló irrecuperablemente -> conclude
    if status_val in (
        GoalStatus.BLOCKED_MISSING_CAPABILITY.value,
        GoalStatus.SATISFIED.value,
        GoalStatus.FAILED.value,
        "blocked_missing_capability",
        "satisfied",
        "failed",
    ):
        return "conclude"

    # Si el LLM determinó que requiere más información con capacidades disponibles -> ciclo a reason
    if status_val in (GoalStatus.NEEDS_MORE_INFO.value, "needs_more_info"):
        return "reason"

    return "conclude"


# ==========================================================
# 3. Ensamblador del Grafo (GraphBuilder)
# ==========================================================


class GraphBuilder:
    """Ensamblador agnóstico de grafos LangGraph (StateGraph) para jg_agente.

    Analiza dinámicamente las capacidades de `CapabilityRegistry` y genera
    un grafo compilado con la topología mínima o expandida según herramientas
    y motores registrados.
    """

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

        nodes.append("evaluate")
        nodes.append("conclude")

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

    def build(
        self,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        interrupt_before: list[str] | None = None,
        interrupt_after: list[str] | None = None,
    ) -> CompiledStateGraph[Any, Any]:
        """Ensambla y compila el StateGraph en un CompiledStateGraph con persistencia y snapshot."""
        topology = self.get_topology()
        self._topology_info = topology

        # Modo degradado: el checkpointer cayó a MemorySaver por fallo de PostgreSQL (Fail-Closed)
        checkpoint_degraded = bool(getattr(checkpointer, "is_degraded", False))

        # LangGraph StateGraph agnóstico
        builder = StateGraph(AgentState)
        has_tools = len(self.registry.list_tools()) > 0

        # --- Definición y registro de Nodos asíncronos ---

        # 1. Observe (Condicional)
        if topology.has_observer:
            observe_handler = self.node_overrides.get("observe")
            if observe_handler:
                builder.add_node("observe", cast(Any, observe_handler))
            else:

                async def _observe_node(s: AgentState) -> dict[str, Any]:
                    return await default_observe_node(s, self.registry)

                builder.add_node("observe", cast(Any, _observe_node))

        # 2. Reason (Obligatorio)
        reason_handler = self.node_overrides.get("reason")
        if reason_handler:
            builder.add_node("reason", cast(Any, reason_handler))
        else:

            async def _reason_node(s: AgentState) -> dict[str, Any]:
                return await default_reason_node(s, self.registry, llm=self.llm)

            builder.add_node("reason", cast(Any, _reason_node))

        # 3. Plan (Condicional)
        if topology.has_planner:
            plan_handler = self.node_overrides.get("plan")
            if plan_handler:
                builder.add_node("plan", cast(Any, plan_handler))
            else:

                async def _plan_node(s: AgentState) -> dict[str, Any]:
                    return await default_plan_node(s, self.registry)

                builder.add_node("plan", cast(Any, _plan_node))

        # 4. Risk Assessment (Condicional)
        if topology.has_risk_assessment:
            risk_handler = self.node_overrides.get("risk_assess")
            if risk_handler:
                builder.add_node("risk_assess", cast(Any, risk_handler))
            else:

                async def _risk_assess_node(s: AgentState) -> dict[str, Any]:
                    if checkpoint_degraded:
                        s = cast(AgentState, {**s, "checkpoint_degraded": True})
                    return await default_risk_assess_node(s, self.registry, self.security_guard)

                builder.add_node("risk_assess", cast(Any, _risk_assess_node))

        # 5. Human Approval (Condicional)
        if topology.has_human_approval:
            approval_handler = self.node_overrides.get("human_approval")
            if approval_handler:
                builder.add_node("human_approval", cast(Any, approval_handler))
            else:

                async def _human_approval_node(s: AgentState) -> dict[str, Any]:
                    return await default_human_approval_node(s, self.registry)

                builder.add_node("human_approval", cast(Any, _human_approval_node))

        # 6. Execute (Obligatorio)
        execute_handler = self.node_overrides.get("execute")
        if execute_handler:
            builder.add_node("execute", cast(Any, execute_handler))
        else:

            async def _execute_node(s: AgentState) -> dict[str, Any]:
                if checkpoint_degraded:
                    s = cast(AgentState, {**s, "checkpoint_degraded": True})
                return await default_execute_node(s, self.registry, self.security_guard)

            builder.add_node("execute", cast(Any, _execute_node))

        # 7. Verify (Condicional)
        if topology.has_verifier:
            verify_handler = self.node_overrides.get("verify")
            if verify_handler:
                builder.add_node("verify", cast(Any, verify_handler))
            else:

                async def _verify_node(s: AgentState) -> dict[str, Any]:
                    return await default_verify_node(s, self.registry)

                builder.add_node("verify", cast(Any, _verify_node))

        # 8. Rollback (Condicional)
        if topology.has_rollback:
            rollback_handler = self.node_overrides.get("rollback")
            if rollback_handler:
                builder.add_node("rollback", cast(Any, rollback_handler))
            else:

                async def _rollback_node(s: AgentState) -> dict[str, Any]:
                    return await default_rollback_node(s, self.registry)

                builder.add_node("rollback", cast(Any, _rollback_node))

        # 9. Evaluate (Obligatorio/Canónico)
        evaluate_handler = self.node_overrides.get("evaluate")
        if evaluate_handler:
            builder.add_node("evaluate", cast(Any, evaluate_handler))
        else:

            async def _evaluate_node(s: AgentState) -> dict[str, Any]:
                return await default_evaluate_node(s, self.registry, llm=self.llm)

            builder.add_node("evaluate", cast(Any, _evaluate_node))

        # 10. Conclude (Obligatorio)
        conclude_handler = self.node_overrides.get("conclude")
        if conclude_handler:
            builder.add_node("conclude", cast(Any, conclude_handler))
        else:

            async def _conclude_node(s: AgentState) -> dict[str, Any]:
                return await default_conclude_node(s, self.registry)

            builder.add_node("conclude", cast(Any, _conclude_node))

        # --- Conexión de Aristas (Edges) ---

        # Conexión inicial desde START
        if topology.has_observer:
            builder.add_edge(START, "observe")
            builder.add_edge("observe", "reason")
        else:
            builder.add_edge(START, "reason")

        # Conexión desde Reason
        reason_destinations: list[str] = ["conclude"]
        if topology.has_planner:
            reason_destinations.append("plan")
        if topology.has_risk_assessment:
            reason_destinations.append("risk_assess")
        if has_tools:
            reason_destinations.append("execute")

        builder.add_conditional_edges(
            "reason",
            lambda s: route_after_reason(
                s,
                has_planner=topology.has_planner,
                has_tools=has_tools,
                has_risk_assessment=topology.has_risk_assessment,
            ),
            path_map=list(set(reason_destinations)),
        )

        # Conexión desde Plan (si existe)
        if topology.has_planner:
            plan_destinations: list[str] = ["conclude"]
            if topology.has_risk_assessment:
                plan_destinations.append("risk_assess")
            else:
                plan_destinations.append("execute")

            builder.add_conditional_edges(
                "plan",
                lambda s: route_after_plan(
                    s,
                    has_risk_assessment=topology.has_risk_assessment,
                ),
                path_map=list(set(plan_destinations)),
            )

        # Conexión desde Risk Assessment (si existe)
        if topology.has_risk_assessment:
            risk_destinations = ["execute", "conclude"]
            if topology.has_human_approval:
                risk_destinations.append("human_approval")
            builder.add_conditional_edges(
                "risk_assess",
                lambda s: route_after_risk_assess(
                    s,
                    has_human_approval=topology.has_human_approval,
                ),
                path_map=list(set(risk_destinations)),
            )

        # Conexión desde Human Approval (si existe)
        if topology.has_human_approval:
            builder.add_conditional_edges(
                "human_approval",
                route_after_human_approval,
                path_map=["execute", "conclude"],
            )

        # Conexión desde Execute
        execute_destinations = ["verify" if topology.has_verifier else "evaluate"]
        if topology.has_rollback:
            execute_destinations.append("rollback")
        builder.add_conditional_edges(
            "execute",
            lambda s: route_after_execute(
                s,
                has_verifier=topology.has_verifier,
                has_rollback=topology.has_rollback,
            ),
            path_map=execute_destinations,
        )

        # Conexión desde Verify (si existe)
        if topology.has_verifier:
            verify_destinations = ["evaluate"] if topology.has_evaluator else ["conclude"]
            if topology.has_rollback:
                verify_destinations.append("rollback")
            builder.add_conditional_edges(
                "verify",
                lambda s: route_after_verify(
                    s,
                    has_rollback=topology.has_rollback,
                    has_evaluator=topology.has_evaluator,
                ),
                path_map=list(set(verify_destinations)),
            )

        # Conexión desde Evaluate (Arista condicional de razonamiento cíclico y guardarraíles)
        eval_destinations = ["reason", "conclude"]
        if topology.has_rollback:
            eval_destinations.append("rollback")
        builder.add_conditional_edges(
            "evaluate",
            lambda s: route_after_evaluation(
                s,
                has_rollback=topology.has_rollback,
            ),
            path_map=list(set(eval_destinations)),
        )

        # Conexión desde Rollback (si existe)
        if topology.has_rollback:
            builder.add_edge("rollback", "conclude")

        # Conexión final desde Conclude hacia END
        builder.add_edge("conclude", END)

        # Persistencia: Si no se suministra checkpointer externo, se utiliza MemorySaver
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
