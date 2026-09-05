"""Pruebas unitarias e integradas para el nodo de pausa HITL y reanudación (human_approval_node).

Verifica la suspensión en checkpoint nativo mediante interrupt(), la recuperación sin
bloqueo de hilos y la reanudación ante comandos externos de aprobación o rechazo (Command(resume=...)).
"""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.core.graph import GraphBuilder, route_after_human_approval
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    ExecutionPlan,
    PlanStep,
    StepStatus,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.human_approval import human_approval_node
from app.plugins.base import PlannerEngine


def dummy_tool_func(**kwargs: Any) -> ToolResult:
    return ToolResult(success=True, output="operacion_completada")


# ==========================================================
# Tests Unitarios para human_approval_node
# ==========================================================


@pytest.mark.asyncio
async def test_human_approval_offline_direct_call() -> None:
    """Verifica que human_approval_node maneje limpiamente la ejecución fuera del contexto LangGraph."""
    state: AgentState = {
        "status": AgentExecutionStatus.AWAITING_APPROVAL,
        "requires_approval": True,
        "approval": None,
        "audit_trail": [],
    }

    result = await human_approval_node(state)

    assert result["status"] == AgentExecutionStatus.AWAITING_APPROVAL
    assert result["human_intervention_required"] is True
    assert result["requires_approval"] is True
    assert isinstance(result["approval"], ApprovalRecord)
    assert result["approval"].status == ApprovalStatus.PENDING

    audits = result["audit_trail"]
    assert len(audits) == 1
    assert audits[0].event_type == "human_approval_requested"
    assert audits[0].details.get("offline") is True


@pytest.mark.asyncio
async def test_human_approval_pre_approved_passthrough() -> None:
    """Verifica que si el estado ya contiene una aprobación válida, continúe sin interrumpir."""
    pre_app = ApprovalRecord(
        status=ApprovalStatus.APPROVED,
        approver="admin_alice",
        notes="Pre-autorizado por política",
    )
    state: AgentState = {
        "status": AgentExecutionStatus.AWAITING_APPROVAL,
        "requires_approval": True,
        "approval": pre_app,
        "audit_trail": [],
    }

    result = await human_approval_node(state)

    assert result["status"] == AgentExecutionStatus.EXECUTING
    assert result["human_intervention_required"] is False
    assert result["requires_approval"] is False
    assert result["approval"] == pre_app

    audits = result["audit_trail"]
    assert len(audits) == 1
    assert audits[0].event_type == "human_approval_completed"
    assert audits[0].actor == "admin_alice"
    assert audits[0].details.get("pre_approved") is True


@pytest.mark.asyncio
async def test_human_approval_pre_rejected_passthrough() -> None:
    """Verifica que si el estado ya contiene un rechazo, finalice sin re-interrumpir."""
    pre_app = ApprovalRecord(
        status=ApprovalStatus.REJECTED,
        approver="secops_bob",
        notes="Operación vetada",
    )
    state: AgentState = {
        "status": AgentExecutionStatus.AWAITING_APPROVAL,
        "requires_approval": True,
        "approval": pre_app,
        "audit_trail": [],
    }

    result = await human_approval_node(state)

    assert result["status"] == AgentExecutionStatus.FAILED
    assert result["human_intervention_required"] is False
    assert result["requires_approval"] is False
    assert result["approval"] == pre_app

    audits = result["audit_trail"]
    assert len(audits) == 1
    assert audits[0].event_type == "human_approval_rejected"
    assert audits[0].actor == "secops_bob"
    assert audits[0].details.get("pre_rejected") is True


def test_route_after_human_approval() -> None:
    """Valida la lógica determinista de bifurcación condicional tras human_approval."""
    # Aprobado -> execute
    state_approved: AgentState = {"approval": ApprovalRecord(status=ApprovalStatus.APPROVED)}
    assert route_after_human_approval(state_approved) == "execute"

    # Auto-aprobado -> execute
    state_auto: AgentState = {"approval": ApprovalRecord(status=ApprovalStatus.AUTO_APPROVED)}
    assert route_after_human_approval(state_auto) == "execute"

    # Rechazado -> conclude
    state_rejected: AgentState = {"approval": ApprovalRecord(status=ApprovalStatus.REJECTED)}
    assert route_after_human_approval(state_rejected) == "conclude"

    # Pendiente o ausente -> conclude
    state_pending: AgentState = {"approval": ApprovalRecord(status=ApprovalStatus.PENDING)}
    assert route_after_human_approval(state_pending) == "conclude"

    state_empty: AgentState = {}
    assert route_after_human_approval(state_empty) == "conclude"


# ==========================================================
# Tests de Integración LangGraph con interrupt() y Command(resume=...)
# ==========================================================


class MockHighRiskPlanner(PlannerEngine):
    """Planner que produce un plan con herramienta de alto riesgo."""

    def __init__(self, high_tool_name: str) -> None:
        self.high_tool_name = high_tool_name

    @property
    def name(self) -> str:
        return "mock_high_risk_planner"

    async def plan(
        self,
        state: AgentState | None = None,
        **kwargs: Any,
    ) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id="plan-hitl-01",
            goal="Ejecutar acción crítica",
            steps=[
                PlanStep(
                    step_id="step-critical",
                    tool_name=self.high_tool_name,
                    description=f"Call {self.high_tool_name}",
                    tool_args={"action": "reboot"},
                )
            ],
        )


@pytest.mark.asyncio
async def test_langgraph_interrupt_and_resume_approved() -> None:
    """Verifica que el grafo pause en human_approval mediante interrupt() y continúe al ser aprobado."""
    registry = CapabilityRegistry()
    critical_tool = AgentTool(
        name="critical_infra_op",
        description="Operación de infraestructura crítica",
        category="infra",
        func=dummy_tool_func,
        risk_level=RiskLevel.HIGH,
    )
    registry.register_tool(critical_tool)

    planner = MockHighRiskPlanner(critical_tool.name)
    registry.register_engine(planner)

    checkpointer = MemorySaver()
    builder = GraphBuilder(registry=registry)
    graph = builder.build(checkpointer=checkpointer)

    thread_id = "test-thread-hitl-approve-01"
    run_config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "messages": [HumanMessage(content="Reiniciar cluster de producción")],
        "request": AgentInput(
            prompt="Reiniciar cluster",
            thread_id=thread_id,
            execution_id="exec-hitl-01",
        ),
        "audit_trail": [],
    }

    # 1. Primera invocación: el grafo debe pausarse en human_approval
    result_interrupted = await graph.ainvoke(initial_state, run_config)

    # Verificar que LangGraph emitió la interrupción nativa
    assert "__interrupt__" in result_interrupted
    interrupt_items = result_interrupted["__interrupt__"]
    assert len(interrupt_items) > 0
    interrupt_payload = interrupt_items[0].value
    assert interrupt_payload["action"] == "human_approval_required"
    assert interrupt_payload["thread_id"] == thread_id

    # Inspeccionar estado guardado en el checkpointer
    saved_state = await graph.aget_state(run_config)
    assert "human_approval" in saved_state.next

    # 2. Segunda invocación: reanudación mediante Command(resume=...) con aprobación
    resume_payload = {
        "approved": True,
        "approver": "security_director",
        "notes": "Autorizado para ventana de mantenimiento",
    }
    resume_command: Command[Any] = Command(resume=resume_payload)

    result_resumed = await graph.ainvoke(resume_command, run_config)

    # Verificar que el grafo continuó por execute y finalizó en conclude
    assert result_resumed.get("status") == AgentExecutionStatus.RESOLVED
    approval = result_resumed.get("approval")
    assert isinstance(approval, ApprovalRecord)
    assert approval.status == ApprovalStatus.APPROVED
    assert approval.approver == "security_director"

    # Verificar que la herramienta de alto riesgo efectivamente se ejecutó
    exec_records = result_resumed.get("execution_records", [])
    assert len(exec_records) == 1
    assert exec_records[0].tool_name == "critical_infra_op"
    assert exec_records[0].status == StepStatus.COMPLETED

    # Verificar registro de auditoría de HITL
    audits = [
        a
        for a in result_resumed.get("audit_trail", [])
        if a.event_type == "human_approval_completed"
    ]
    assert len(audits) >= 1
    assert audits[0].actor == "security_director"


@pytest.mark.asyncio
async def test_langgraph_interrupt_and_resume_rejected() -> None:
    """Verifica que el grafo pause en human_approval y finalice con FAILED al ser rechazado."""
    registry = CapabilityRegistry()
    critical_tool = AgentTool(
        name="dangerous_cleanup",
        description="Borrado masivo de recursos",
        category="storage",
        func=dummy_tool_func,
        risk_level=RiskLevel.CRITICAL,
    )
    registry.register_tool(critical_tool)

    planner = MockHighRiskPlanner(critical_tool.name)
    registry.register_engine(planner)

    checkpointer = MemorySaver()
    builder = GraphBuilder(registry=registry)
    graph = builder.build(checkpointer=checkpointer)

    thread_id = "test-thread-hitl-reject-01"
    run_config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "messages": [HumanMessage(content="Limpiar base de datos")],
        "request": AgentInput(
            prompt="Limpiar base de datos",
            thread_id=thread_id,
            execution_id="exec-hitl-02",
        ),
        "audit_trail": [],
    }

    # 1. Primera invocación: pausa en interrupt
    result_interrupted = await graph.ainvoke(initial_state, run_config)
    assert "__interrupt__" in result_interrupted

    # 2. Segunda invocación: rechazo mediante Command(resume=...)
    resume_payload = {
        "approved": False,
        "approver": "secops_lead",
        "notes": "Rechazado: fuera de ventana de mantenimiento",
    }
    resume_command: Command[Any] = Command(resume=resume_payload)

    result_resumed = await graph.ainvoke(resume_command, run_config)

    # Verificar que el grafo enrutó a conclude marcando estado FAILED
    assert result_resumed.get("status") == AgentExecutionStatus.FAILED
    approval = result_resumed.get("approval")
    assert isinstance(approval, ApprovalRecord)
    assert approval.status == ApprovalStatus.REJECTED
    assert approval.approver == "secops_lead"

    # Verificar que la herramienta peligrosa NO se ejecutó
    exec_records = result_resumed.get("execution_records", [])
    assert len(exec_records) == 0

    # Verificar auditoría de rechazo
    rejections = [
        a
        for a in result_resumed.get("audit_trail", [])
        if a.event_type == "human_approval_rejected"
    ]
    assert len(rejections) >= 1
    assert rejections[0].actor == "secops_lead"
