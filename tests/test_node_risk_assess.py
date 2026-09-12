"""Pruebas unitarias e integradas para el nodo de evaluación de riesgo (risk_assess_node).

Verifica la detección de acciones con RiskLevel >= HIGH, el marcado estricto de
requires_approval=True, la contención de inyecciones y violaciones de seguridad,
la preservación de aprobaciones previas y el enrutamiento hacia human_approval en LangGraph.
"""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.graph import GraphBuilder
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput, UserContext
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    PolicyDecision,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.risk_assess import risk_assess_node
from app.plugins.base import PlannerEngine


def dummy_tool_func(**kwargs: Any) -> ToolResult:
    return ToolResult(success=True, output="ok")


# ==========================================================
# Tests Unitarios para risk_assess_node
# ==========================================================


@pytest.mark.asyncio
async def test_risk_assess_high_risk_plan_requires_approval() -> None:
    """Verifica que un plan con paso RiskLevel.HIGH marque requires_approval=True y AWAITING_APPROVAL."""
    registry = CapabilityRegistry()
    high_tool = AgentTool(
        name="high_risk_op",
        description="Operación sensible",
        category="admin",
        func=dummy_tool_func,
        risk_level=RiskLevel.HIGH,
    )
    registry.register_tool(high_tool)

    plan = ExecutionPlan(
        plan_id="plan-high-01",
        goal="Modificar configuración de producción",
        steps=[
            PlanStep(
                step_id="step-1",
                tool_name="high_risk_op",
                tool_args={"target": "prod-cluster"},
                risk_level=RiskLevel.HIGH,
            )
        ],
        estimated_risk=RiskLevel.HIGH,
    )

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-ra-01",
            thread_id="thread-ra-01",
            prompt="Configurar prod",
        ),
        "plan": plan,
        "status": AgentExecutionStatus.PLANNING,
    }

    result = await risk_assess_node(state, registry=registry)

    assert result["requires_approval"] is True
    assert result["human_intervention_required"] is True
    assert result["status"] == AgentExecutionStatus.AWAITING_APPROVAL
    assert result["risk_assessment"]["decision"] == PolicyDecision.REQUIRE_HUMAN_APPROVAL.value
    assert result["risk_assessment"]["risk_level"] == RiskLevel.HIGH.value

    approval = result.get("approval")
    assert isinstance(approval, ApprovalRecord)
    assert approval.status == ApprovalStatus.PENDING

    assert len(result["audit_trail"]) == 1
    audit = result["audit_trail"][0]
    assert audit.event_type == "risk_assessment_completed"
    assert audit.details["requires_approval"] is True
    assert audit.details["risk_level"] == RiskLevel.HIGH.value


@pytest.mark.asyncio
async def test_risk_assess_critical_risk_plan_requires_approval() -> None:
    """Verifica que un paso CRITICAL active can_cause_data_loss y requires_approval=True."""
    registry = CapabilityRegistry()

    plan = ExecutionPlan(
        plan_id="plan-crit-01",
        goal="Purgar base de datos",
        steps=[
            PlanStep(
                step_id="step-crit",
                tool_name="db_purge",
                tool_args={"all": True},
                risk_level=RiskLevel.CRITICAL,
            )
        ],
        estimated_risk=RiskLevel.CRITICAL,
    )

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-ra-02",
            thread_id="thread-ra-02",
            prompt="Purgar DB",
        ),
        "plan": plan,
    }

    result = await risk_assess_node(state, registry=registry)

    assert result["requires_approval"] is True
    assert result["risk_assessment"]["risk_level"] == RiskLevel.CRITICAL.value
    assert result["risk_assessment"]["can_cause_data_loss"] is True
    assert result["status"] == AgentExecutionStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_risk_assess_low_risk_plan_auto_allowed() -> None:
    """Verifica que un plan de bajo riesgo no requiera aprobación humana (ALLOW)."""
    registry = CapabilityRegistry()
    safe_tool = AgentTool(
        name="read_metrics",
        description="Lectura",
        category="metrics",
        func=dummy_tool_func,
        risk_level=RiskLevel.LOW,
    )
    registry.register_tool(safe_tool)

    plan = ExecutionPlan(
        plan_id="plan-safe-01",
        goal="Leer telemetría",
        steps=[
            PlanStep(
                step_id="step-1",
                tool_name="read_metrics",
                tool_args={},
                risk_level=RiskLevel.LOW,
            )
        ],
        estimated_risk=RiskLevel.LOW,
    )

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-ra-03",
            thread_id="thread-ra-03",
            prompt="Leer métricas",
        ),
        "plan": plan,
    }

    result = await risk_assess_node(state, registry=registry)

    assert result["requires_approval"] is False
    assert result["human_intervention_required"] is False
    assert result["risk_assessment"]["decision"] == PolicyDecision.ALLOW.value
    assert "status" not in result or result["status"] != AgentExecutionStatus.AWAITING_APPROVAL
    assert "approval" not in result


@pytest.mark.asyncio
async def test_risk_assess_tool_calls_requires_approval() -> None:
    """Verifica evaluación de riesgo sobre tool_calls directas en ausencia de plan formal."""
    registry = CapabilityRegistry()
    nuke_tool = AgentTool(
        name="nuke_service",
        description="Eliminar servicio",
        category="ops",
        func=dummy_tool_func,
        risk_level=RiskLevel.HIGH,
    )
    registry.register_tool(nuke_tool)

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-ra-04",
            thread_id="thread-ra-04",
            prompt="Eliminar servicio de pruebas",
        ),
        "intent": IntentModel(
            goal="Eliminar servicio",
            action_type="act",
            parameters={"tool_calls": [{"name": "nuke_service", "args": {"svc": "test"}}]},
        ),
    }

    result = await risk_assess_node(state, registry=registry)

    assert result["requires_approval"] is True
    assert result["human_intervention_required"] is True
    assert result["risk_assessment"]["risk_level"] == RiskLevel.HIGH.value
    assert result["status"] == AgentExecutionStatus.AWAITING_APPROVAL


@pytest.mark.asyncio
async def test_risk_assess_denies_shell_injection() -> None:
    """Verifica que SecurityGuard detecte inyección y deniegue la operación (DENY)."""
    registry = CapabilityRegistry()
    cmd_tool = AgentTool(
        name="run_cmd",
        description="Ejecución",
        category="system",
        func=dummy_tool_func,
        risk_level=RiskLevel.MEDIUM,
    )
    registry.register_tool(cmd_tool)

    plan = ExecutionPlan(
        plan_id="plan-inj-01",
        goal="Ataque de inyección",
        steps=[
            PlanStep(
                step_id="s1",
                tool_name="run_cmd",
                tool_args={"command": "status && rm -rf /etc"},
                risk_level=RiskLevel.MEDIUM,
            )
        ],
    )

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-ra-05",
            thread_id="thread-ra-05",
            prompt="Inyección",
        ),
        "plan": plan,
    }

    result = await risk_assess_node(state, registry=registry)

    assert result["risk_assessment"]["decision"] == PolicyDecision.DENY.value
    assert result["circuit_breaker_active"] is True
    assert result["status"] == AgentExecutionStatus.FAILED
    assert (
        "Inyección" in result["risk_assessment"]["reason"]
        or "Violación" in result["risk_assessment"]["reason"]
    )


@pytest.mark.asyncio
async def test_risk_assess_preserves_existing_approved_status() -> None:
    """Verifica que si la operación ya estaba aprobada (reanudación HITL), no se sobreescriba a PENDING."""
    registry = CapabilityRegistry()
    high_tool = AgentTool(
        name="high_tool",
        description="Alta prioridad",
        category="core",
        func=dummy_tool_func,
        risk_level=RiskLevel.HIGH,
    )
    registry.register_tool(high_tool)

    plan = ExecutionPlan(
        plan_id="plan-app-01",
        goal="Acción ya aprobada",
        steps=[
            PlanStep(
                step_id="step-1",
                tool_name="high_tool",
                tool_args={},
                risk_level=RiskLevel.HIGH,
            )
        ],
    )

    existing_approval = ApprovalRecord(
        status=ApprovalStatus.APPROVED,
        notes="Aprobado manualmente por operador en jg_dashboard",
    )

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-ra-06",
            thread_id="thread-ra-06",
            prompt="Reanudación",
        ),
        "plan": plan,
        "approval": existing_approval,
    }

    result = await risk_assess_node(state, registry=registry)

    # El riesgo sigue siendo HIGH y requiere aprobación conceptual
    assert result["requires_approval"] is True
    # Pero el registro no se sobreescribe a PENDING en el retorno
    assert "approval" not in result


# ==========================================================
# Test de Integración con Grafo LangGraph y Enrutamiento HITL
# ==========================================================


class HighRiskPlanner(PlannerEngine):
    """PlannerEngine que formula un plan con una acción de riesgo HIGH."""

    @property
    def name(self) -> str:
        return "high_risk_planner"

    async def create_plan(self, state: AgentState) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id="plan-graph-hitl-01",
            goal="Operación crítica en cluster",
            steps=[
                PlanStep(
                    step_id="step-restart",
                    tool_name="cluster_restart_tool",
                    tool_args={"cluster_id": "c-01"},
                    risk_level=RiskLevel.HIGH,
                )
            ],
            estimated_risk=RiskLevel.HIGH,
        )


@pytest.mark.asyncio
async def test_risk_assess_graph_integration_routes_to_human_approval() -> None:
    """Verifica que el grafo LangGraph transite plan -> risk_assess -> human_approval ante riesgo HIGH."""
    registry = CapabilityRegistry()
    registry.register_engine(HighRiskPlanner())

    cluster_tool = AgentTool(
        name="cluster_restart_tool",
        description="Reinicio de cluster",
        category="devops",
        func=dummy_tool_func,
        risk_level=RiskLevel.HIGH,
    )
    registry.register_tool(cluster_tool)

    builder = GraphBuilder(registry)
    topology = builder.get_topology()

    assert topology.has_planner is True
    assert topology.has_risk_assessment is True
    assert topology.has_human_approval is True
    assert "risk_assess" in topology.nodes
    assert "human_approval" in topology.nodes

    graph = builder.build(interrupt_before=["human_approval"])
    config: RunnableConfig = {"configurable": {"thread_id": "thread-hitl-graph-01"}}

    initial_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-hitl-graph-01",
            thread_id="thread-hitl-graph-01",
            prompt="Reiniciar cluster de producción",
        ),
        "messages": [HumanMessage(content="Reiniciar cluster")],
        "status": AgentExecutionStatus.IDLE,
    }

    await graph.ainvoke(initial_state, config=config)

    # Verificar que el grafo se pausó en el checkpoint justo antes de human_approval
    snapshot = await graph.aget_state(config)
    assert snapshot is not None
    assert snapshot.next == ("human_approval",)

    # Debe haberse evaluado el riesgo y marcado el estado para HITL
    assert snapshot.values["requires_approval"] is True
    assert snapshot.values["human_intervention_required"] is True
    assert snapshot.values["status"] == AgentExecutionStatus.AWAITING_APPROVAL

    approval = snapshot.values.get("approval")
    assert approval is not None
    approval_status = (
        approval.status if isinstance(approval, ApprovalRecord) else approval.get("status")
    )
    assert approval_status in (ApprovalStatus.PENDING, ApprovalStatus.PENDING.value)

    # Verificar presencia de trazas de planning y risk_assessment en audit_trail
    events = [a.event_type for a in snapshot.values["audit_trail"]]
    assert "planning_completed" in events
    assert "risk_assessment_completed" in events


@pytest.mark.asyncio
async def test_risk_assess_denies_unauthorized_caller_without_permissions() -> None:
    """Verifica que si el invocador no posee permisos, risk_assess NO le auto-asigne
    los permisos requeridos y deniegue la ejecución [AGENTE-SEC-04]."""
    registry = CapabilityRegistry()
    protected_tool = AgentTool(
        name="protected_admin_op",
        description="Operación protegida",
        category="admin",
        func=dummy_tool_func,
        risk_level=RiskLevel.LOW,
        required_permissions=["infra:restart"],
    )
    registry.register_tool(protected_tool)

    plan = ExecutionPlan(
        plan_id="plan-sec-04",
        goal="Intentar ejecución sin permisos",
        steps=[
            PlanStep(
                step_id="step-1",
                tool_name="protected_admin_op",
                risk_level=RiskLevel.LOW,
            )
        ],
        estimated_risk=RiskLevel.LOW,
    )

    # Invocador anónimo/sin contexto de usuario ni permisos
    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-sec-04",
            thread_id="thread-sec-04",
            prompt="Ejecutar admin op",
        ),
        "plan": plan,
    }

    result = await risk_assess_node(state, registry=registry)

    # Debe ser denegado por falta de permisos (CWE-285 mitigado)
    assert result["status"] == AgentExecutionStatus.FAILED
    assert result["risk_assessment"]["decision"] == PolicyDecision.DENY.value
    assert "Permisos insuficientes" in result["risk_assessment"]["reason"]
    assert "infra:restart" in result["risk_assessment"]["reason"]


@pytest.mark.asyncio
async def test_risk_assess_allows_authorized_caller_with_permission() -> None:
    """Verifica que un invocador con el permiso requerido sea evaluado favorablemente."""
    registry = CapabilityRegistry()
    protected_tool = AgentTool(
        name="protected_admin_op",
        description="Operación protegida",
        category="admin",
        func=dummy_tool_func,
        risk_level=RiskLevel.LOW,
        required_permissions=["infra:restart"],
    )
    registry.register_tool(protected_tool)

    plan = ExecutionPlan(
        plan_id="plan-sec-04-ok",
        goal="Ejecución con permiso explícito",
        steps=[
            PlanStep(
                step_id="step-1",
                tool_name="protected_admin_op",
                risk_level=RiskLevel.LOW,
            )
        ],
        estimated_risk=RiskLevel.LOW,
    )

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-sec-04-ok",
            thread_id="thread-sec-04-ok",
            prompt="Ejecutar con permisos",
            user_context=UserContext(
                user_id="op-1",
                role="operator",
                permissions=["infra:restart"],
            ),
        ),
        "plan": plan,
    }

    result = await risk_assess_node(state, registry=registry)

    assert result["risk_assessment"]["decision"] == PolicyDecision.ALLOW.value
    assert result.get("status") != AgentExecutionStatus.FAILED


@pytest.mark.asyncio
async def test_risk_assess_allows_admin_caller_with_wildcard() -> None:
    """Verifica que un usuario con rol admin obtenga wildcard de permisos y sea autorizado."""
    registry = CapabilityRegistry()
    protected_tool = AgentTool(
        name="protected_admin_op",
        description="Operación protegida",
        category="admin",
        func=dummy_tool_func,
        risk_level=RiskLevel.LOW,
        required_permissions=["infra:restart"],
    )
    registry.register_tool(protected_tool)

    plan = ExecutionPlan(
        plan_id="plan-sec-04-admin",
        goal="Ejecución por admin",
        steps=[
            PlanStep(
                step_id="step-1",
                tool_name="protected_admin_op",
                risk_level=RiskLevel.LOW,
            )
        ],
        estimated_risk=RiskLevel.LOW,
    )

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-sec-04-admin",
            thread_id="thread-sec-04-admin",
            prompt="Ejecutar como admin",
            user_context=UserContext(
                user_id="admin-1",
                role="admin",
            ),
        ),
        "plan": plan,
    }

    result = await risk_assess_node(state, registry=registry)

    assert result["risk_assessment"]["decision"] == PolicyDecision.ALLOW.value
    assert result.get("status") != AgentExecutionStatus.FAILED
