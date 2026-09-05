"""Tests unitarios e integrados para el nodo base de ejecución (execute)."""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.core.graph import GraphBuilder
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    StepStatus,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.execute import execute_node

# ==========================================================
# Herramientas de Prueba (Mocks)
# ==========================================================


def safe_tool_a(query: str = "") -> ToolResult:
    return ToolResult(
        success=True,
        output=f"a_result: {query}",
        duration_ms=10.0,
    )


def safe_tool_b(target: str = "") -> ToolResult:
    return ToolResult(
        success=True,
        output=f"b_result: {target}",
        duration_ms=15.0,
    )


def reversible_tool_fn(action: str = "") -> ToolResult:
    return ToolResult(
        success=True,
        output=f"executed: {action}",
        duration_ms=20.0,
        rollback_context={"backup_file": "/tmp/backup.tar.gz", "snapshot_id": "snap-999"},
    )


def rollback_tool_fn(ctx: dict[str, Any]) -> ToolResult:
    return ToolResult(success=True, output=f"rolled_back: {ctx.get('snapshot_id')}")


def failing_tool_fn(**kwargs: Any) -> ToolResult:
    return ToolResult(
        success=False,
        error="Network timeout connecting to upstream service",
        duration_ms=50.0,
    )


def high_risk_tool_fn(action: str = "") -> ToolResult:
    return ToolResult(
        success=True,
        output=f"high_risk_done: {action}",
        duration_ms=30.0,
    )


async def async_tool_fn(param: str = "") -> ToolResult:
    return ToolResult(
        success=True,
        output=f"async_executed: {param}",
        duration_ms=25.0,
    )


@pytest.fixture
def test_registry() -> CapabilityRegistry:
    """Fixture con registro de capacidades poblado con herramientas mock."""
    registry = CapabilityRegistry()
    registry.register_tool(
        AgentTool(
            name="tool_a",
            description="Herramienta A segura",
            category="test",
            func=safe_tool_a,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register_tool(
        AgentTool(
            name="tool_b",
            description="Herramienta B segura",
            category="test",
            func=safe_tool_b,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register_tool(
        AgentTool(
            name="reversible_tool",
            description="Herramienta con rollback context",
            category="test",
            func=reversible_tool_fn,
            rollback_func=rollback_tool_fn,
            reversible=True,
            risk_level=RiskLevel.MEDIUM,
        )
    )
    registry.register_tool(
        AgentTool(
            name="failing_tool",
            description="Herramienta que siempre falla",
            category="test",
            func=failing_tool_fn,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register_tool(
        AgentTool(
            name="high_risk_tool",
            description="Herramienta de alto riesgo",
            category="test",
            func=high_risk_tool_fn,
            risk_level=RiskLevel.HIGH,
            required_permissions=["admin:deploy"],
        )
    )
    registry.register_tool(
        AgentTool(
            name="async_tool",
            description="Herramienta asíncrona",
            category="test",
            func=async_tool_fn,
            risk_level=RiskLevel.LOW,
        )
    )
    return registry


# ==========================================================
# Suites de Prueba para execute_node
# ==========================================================


class TestExecuteNode:
    """Pruebas unitarias para el nodo cognitivo execute_node."""

    @pytest.mark.asyncio
    async def test_execute_node_sequential_success(self, test_registry: CapabilityRegistry) -> None:
        """Verifica la ejecución secuencial ordenada de múltiples pasos exitosos."""
        plan = ExecutionPlan(
            plan_id="plan-seq-01",
            goal="Ejecutar A y B en orden",
            steps=[
                PlanStep(step_id="s1", tool_name="tool_a", tool_args={"query": "consulta 1"}),
                PlanStep(step_id="s2", tool_name="tool_b", tool_args={"target": "nodo-prod"}),
            ],
        )

        state: AgentState = {
            "plan": plan,
            "status": AgentExecutionStatus.PLANNING,
        }

        result = await execute_node(state, test_registry)

        assert result["status"] == AgentExecutionStatus.EXECUTING
        records = result["execution_records"]
        assert len(records) == 2

        assert records[0].step_id == "s1"
        assert records[0].tool_name == "tool_a"
        assert records[0].status == StepStatus.COMPLETED
        assert "a_result: consulta 1" in str(records[0].output)
        assert records[0].duration_ms >= 0.0

        assert records[1].step_id == "s2"
        assert records[1].tool_name == "tool_b"
        assert records[1].status == StepStatus.COMPLETED
        assert "b_result: nodo-prod" in str(records[1].output)

        assert len(result["errors"]) == 0
        assert len(result["audit_trail"]) == 1
        audit = result["audit_trail"][0]
        assert audit.event_type == "execute_completed"
        assert audit.details["steps_executed"] == 2
        assert audit.details["success_count"] == 2
        assert audit.details["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_execute_node_captures_rollback_context(
        self, test_registry: CapabilityRegistry
    ) -> None:
        """Verifica que rollback_context se almacene rigurosamente en StepExecutionRecord."""
        plan = ExecutionPlan(
            plan_id="plan-rb-01",
            goal="Ejecutar acción reversible",
            steps=[
                PlanStep(
                    step_id="step-rev-1",
                    tool_name="reversible_tool",
                    tool_args={"action": "modificar_conf"},
                    reversible=True,
                )
            ],
        )

        state: AgentState = {"plan": plan}
        result = await execute_node(state, test_registry)

        records = result["execution_records"]
        assert len(records) == 1
        assert records[0].status == StepStatus.COMPLETED
        assert records[0].rollback_context is not None
        assert records[0].rollback_context["backup_file"] == "/tmp/backup.tar.gz"
        assert records[0].rollback_context["snapshot_id"] == "snap-999"

    @pytest.mark.asyncio
    async def test_execute_node_captures_failure_and_halts(
        self, test_registry: CapabilityRegistry
    ) -> None:
        """Verifica contención secuencial: si un paso falla, se abortan pasos posteriores."""
        plan = ExecutionPlan(
            plan_id="plan-fail-01",
            goal="Paso fallido debe detener la cadena",
            steps=[
                PlanStep(step_id="step-fail", tool_name="failing_tool", tool_args={}),
                PlanStep(step_id="step-should-skip", tool_name="tool_a", tool_args={}),
            ],
        )

        state: AgentState = {"plan": plan}
        result = await execute_node(state, test_registry)

        records = result["execution_records"]
        # Debe haberse ejecutado solo el primer paso
        assert len(records) == 1
        assert records[0].step_id == "step-fail"
        assert records[0].status == StepStatus.FAILED
        assert "Network timeout" in str(records[0].error)

        errors = result["errors"]
        assert len(errors) == 1
        assert errors[0].code == "TOOL_EXECUTION_FAILED"
        assert "Network timeout" in errors[0].message

        audit = result["audit_trail"][0]
        assert audit.details["success_count"] == 0
        assert audit.details["failed_count"] == 1

    @pytest.mark.asyncio
    async def test_execute_node_tool_not_found(self, test_registry: CapabilityRegistry) -> None:
        """Verifica que una herramienta inexistente en el registro genere un error graceful."""
        plan = ExecutionPlan(
            plan_id="plan-missing-01",
            goal="Herramienta desconocida",
            steps=[
                PlanStep(
                    step_id="step-missing",
                    tool_name="herramienta_fantasma",
                    tool_args={},
                )
            ],
        )

        state: AgentState = {"plan": plan}
        result = await execute_node(state, test_registry)

        records = result["execution_records"]
        assert len(records) == 1
        assert records[0].status == StepStatus.FAILED
        assert "no existe en el CapabilityRegistry" in str(records[0].error)

        errors = result["errors"]
        assert len(errors) == 1
        assert errors[0].code == "TOOL_NOT_FOUND"
        assert errors[0].fatal is True

    @pytest.mark.asyncio
    async def test_execute_node_from_tool_calls_with_messages(
        self, test_registry: CapabilityRegistry
    ) -> None:
        """Verifica que si no hay plan estructurado pero hay tool_calls, genere ToolMessage."""
        intent = IntentModel(
            goal="Llamada reactiva de herramienta",
            action_type="act",
            parameters={
                "tool_calls": [
                    {
                        "id": "call_12345",
                        "name": "tool_a",
                        "args": {"query": "hola mundo"},
                    }
                ]
            },
        )

        state: AgentState = {
            "intent": intent,
            "status": AgentExecutionStatus.REASONING,
        }

        result = await execute_node(state, test_registry)

        records = result["execution_records"]
        assert len(records) == 1
        assert records[0].step_id == "call_12345"
        assert records[0].tool_name == "tool_a"
        assert records[0].status == StepStatus.COMPLETED

        # Verificación del mensaje ToolMessage emitido para la conversación
        assert "messages" in result
        messages = result["messages"]
        assert len(messages) == 1
        assert isinstance(messages[0], ToolMessage)
        assert messages[0].tool_call_id == "call_12345"
        assert "a_result: hola mundo" in messages[0].content

    @pytest.mark.asyncio
    async def test_execute_node_hitl_approval_bypass(
        self, test_registry: CapabilityRegistry
    ) -> None:
        """Verifica que si la aprobación previa es APPROVED, se elude el bloqueo de alto riesgo."""
        plan = ExecutionPlan(
            plan_id="plan-hitl-appr",
            goal="Operación aprobada por humano",
            steps=[
                PlanStep(
                    step_id="step-hr-1",
                    tool_name="high_risk_tool",
                    tool_args={"action": "deploy_v2"},
                    risk_level=RiskLevel.HIGH,
                )
            ],
        )

        state: AgentState = {
            "plan": plan,
            "approval": ApprovalRecord(
                status=ApprovalStatus.APPROVED,
                approver="tech-lead",
                notes="Aprobado en revisión técnica",
            ),
        }

        result = await execute_node(state, test_registry)

        records = result["execution_records"]
        assert len(records) == 1
        assert records[0].status == StepStatus.COMPLETED
        assert "high_risk_done: deploy_v2" in str(records[0].output)
        assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    async def test_execute_node_hitl_blocked_without_approval(
        self, test_registry: CapabilityRegistry
    ) -> None:
        """Verifica que sin aprobación previa, una herramienta de alto riesgo se bloquee con fallo."""
        plan = ExecutionPlan(
            plan_id="plan-hitl-blocked",
            goal="Operación no aprobada",
            steps=[
                PlanStep(
                    step_id="step-hr-blocked",
                    tool_name="high_risk_tool",
                    tool_args={"action": "deploy_prod"},
                    risk_level=RiskLevel.HIGH,
                )
            ],
        )

        state: AgentState = {
            "plan": plan,
            "approval": ApprovalRecord(status=ApprovalStatus.PENDING),
        }

        result = await execute_node(state, test_registry)

        records = result["execution_records"]
        assert len(records) == 1
        assert records[0].status == StepStatus.FAILED
        assert "SecurityGuard" in str(records[0].error)
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_execute_node_async_tool_support(self, test_registry: CapabilityRegistry) -> None:
        """Verifica el soporte y resolución transparente de herramientas asíncronas (async def)."""
        plan = ExecutionPlan(
            plan_id="plan-async-01",
            goal="Ejecutar herramienta asíncrona",
            steps=[
                PlanStep(
                    step_id="step-async-1",
                    tool_name="async_tool",
                    tool_args={"param": "data_async"},
                )
            ],
        )

        state: AgentState = {"plan": plan}
        result = await execute_node(state, test_registry)

        records = result["execution_records"]
        assert len(records) == 1
        assert records[0].status == StepStatus.COMPLETED
        assert "async_executed: data_async" in str(records[0].output)

    @pytest.mark.asyncio
    async def test_execute_node_integrated_in_graph(
        self, test_registry: CapabilityRegistry
    ) -> None:
        """Verifica que execute_node funcione armónicamente dentro del StateGraph compilado."""
        builder = GraphBuilder(test_registry)
        graph = builder.build()

        config: RunnableConfig = {"configurable": {"thread_id": "thread-exec-int-01"}}
        initial_state: AgentState = {
            "request": AgentInput(
                execution_id="exec-int-01",
                thread_id="thread-exec-int-01",
                prompt="Ejecutar tool_a",
            ),
            "messages": [HumanMessage(content="ejecutar tool_a")],
            "status": AgentExecutionStatus.IDLE,
        }

        result = await graph.ainvoke(initial_state, config=config)

        assert result["status"] == AgentExecutionStatus.RESOLVED
        assert len(result["execution_records"]) >= 1
        rec = result["execution_records"][0]
        assert rec.tool_name == "tool_a"
        assert rec.status == StepStatus.COMPLETED
        assert result["is_resolved"] is True
