"""Pruebas unitarias e integradas para los nodos verify y rollback en jg_agente.

Verifica la comprobación post-ejecución con VerifierEngine, la detección de anomalías,
la activación automática de compensaciones en orden inverso para herramientas reversibles
y el enrutamiento determinista en LangGraph.
"""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver

from app.core.graph import GraphBuilder, route_after_verify
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    StepExecutionRecord,
    StepStatus,
    VerificationStatus,
)
from app.models.tools import AgentTool, ToolResult
from app.nodes.rollback import rollback_node
from app.nodes.verify import verify_node
from app.plugins.base import VerifierEngine

# ==========================================================
# Fixtures y Mocks Auxiliares
# ==========================================================


class MockPassingVerifier(VerifierEngine):
    """Motor de verificación que siempre aprueba el estado del entorno."""

    @property
    def name(self) -> str:
        return "mock_passing_verifier"

    async def verify(self, state: AgentState) -> dict[str, Any]:
        return {"status": "pass", "checks": {"health": "ok", "latency_ms": 12.5}}


class MockFailingVerifier(VerifierEngine):
    """Motor de verificación que detecta anomalías en el entorno."""

    @property
    def name(self) -> str:
        return "mock_failing_verifier"

    async def verify(self, state: AgentState) -> dict[str, Any]:
        return {
            "status": "fail",
            "reason": "Anomalía de integridad detectada: servicio no responde tras la operación.",
            "checks": {"health": "unreachable"},
        }


class MockExplodingVerifier(VerifierEngine):
    """Motor de verificación que lanza una excepción imprevista."""

    @property
    def name(self) -> str:
        return "mock_exploding_verifier"

    def verify(self, state: AgentState) -> dict[str, Any]:
        raise ConnectionResetError("Conexión perdida con el sensor de verificación")


# ==========================================================
# 1. Tests Unitarios de verify_node
# ==========================================================


@pytest.mark.asyncio
async def test_verify_node_with_passing_verifier() -> None:
    """Verifica que un VerifierEngine exitoso marque VerificationStatus.PASS y genere auditoría."""
    registry = CapabilityRegistry()
    registry.register_engine(MockPassingVerifier())

    state: AgentState = {
        "execution_records": [
            StepExecutionRecord(
                step_id="step-1",
                tool_name="test_tool",
                status=StepStatus.COMPLETED,
            )
        ],
        "errors": [],
        "audit_trail": [],
    }

    result = await verify_node(state, registry=registry)

    assert result["status"] == AgentExecutionStatus.VERIFYING
    assert len(result["verification_results"]) == 1
    v_res = result["verification_results"][0]
    assert v_res["status"] == VerificationStatus.PASS.value
    assert v_res["details"]["verified_by"] == "mock_passing_verifier"
    assert v_res["details"]["checks"]["health"] == "ok"

    audits = result["audit_trail"]
    assert len(audits) == 1
    assert audits[0].event_type == "verification_completed"
    assert audits[0].actor == "mock_passing_verifier"
    assert "errors" not in result


@pytest.mark.asyncio
async def test_verify_node_with_failing_verifier() -> None:
    """Verifica que un VerifierEngine anómalo marque VerificationStatus.FAIL y añada error operacional."""
    registry = CapabilityRegistry()
    registry.register_engine(MockFailingVerifier())

    state: AgentState = {
        "execution_records": [
            StepExecutionRecord(
                step_id="step-1",
                tool_name="test_tool",
                status=StepStatus.COMPLETED,
            )
        ],
        "errors": [],
        "audit_trail": [],
    }

    result = await verify_node(state, registry=registry)

    assert result["status"] == AgentExecutionStatus.VERIFYING
    assert len(result["verification_results"]) == 1
    v_res = result["verification_results"][0]
    assert v_res["status"] == VerificationStatus.FAIL.value
    assert "Anomalía de integridad" in v_res["details"]["reason"]

    audits = result["audit_trail"]
    assert len(audits) == 1
    assert audits[0].event_type == "verification_failed"

    assert len(result.get("errors", [])) == 1
    assert result["errors"][0].code == "VERIFICATION_FAILED"


@pytest.mark.asyncio
async def test_verify_node_fallback_autonomous() -> None:
    """Verifica el fallback de comprobación autónoma en ausencia de VerifierEngine."""
    # Sin errores -> PASS
    state_ok: AgentState = {
        "execution_records": [
            StepExecutionRecord(step_id="s1", tool_name="t1", status=StepStatus.COMPLETED)
        ],
        "errors": [],
    }
    res_ok = await verify_node(state_ok, registry=None)
    assert res_ok["verification_results"][0]["status"] == VerificationStatus.PASS.value
    assert res_ok["verification_results"][0]["details"].get("fallback") is True

    # Con paso fallido -> FAIL
    state_fail: AgentState = {
        "execution_records": [
            StepExecutionRecord(
                step_id="s1", tool_name="t1", status=StepStatus.FAILED, error="Error fatal"
            )
        ],
        "errors": [],
    }
    res_fail = await verify_node(state_fail, registry=None)
    assert res_fail["verification_results"][0]["status"] == VerificationStatus.FAIL.value
    assert len(res_fail.get("errors", [])) == 1


@pytest.mark.asyncio
async def test_verify_node_engine_exception_resilience() -> None:
    """Verifica que una excepción en VerifierEngine sea capturada y registrada como FAIL."""
    registry = CapabilityRegistry()
    registry.register_engine(MockExplodingVerifier())

    state: AgentState = {
        "execution_records": [
            StepExecutionRecord(step_id="s1", tool_name="t1", status=StepStatus.COMPLETED)
        ],
        "errors": [],
    }

    result = await verify_node(state, registry=registry)
    assert result["verification_results"][0]["status"] == VerificationStatus.FAIL.value
    assert "Conexión perdida" in result["verification_results"][0]["details"]["error"]


# ==========================================================
# 2. Tests Unitarios de rollback_node
# ==========================================================


@pytest.mark.asyncio
async def test_rollback_node_executes_in_reverse_order() -> None:
    """Verifica que rollback_node ejecute las compensaciones en orden inverso al de ejecución."""
    call_order: list[str] = []

    def rollback_t1(ctx: dict[str, Any]) -> ToolResult:
        call_order.append(f"rollback_t1_{ctx.get('id')}")
        return ToolResult(success=True, output="t1 revertido")

    def rollback_t2(ctx: dict[str, Any]) -> ToolResult:
        call_order.append(f"rollback_t2_{ctx.get('id')}")
        return ToolResult(success=True, output="t2 revertido")

    tool1 = AgentTool(
        name="tool_1",
        description="Tool reversible 1",
        category="test",
        func=lambda **kwargs: ToolResult(success=True, output="t1"),
        rollback_func=rollback_t1,
        reversible=True,
    )
    tool2 = AgentTool(
        name="tool_2",
        description="Tool reversible 2",
        category="test",
        func=lambda **kwargs: ToolResult(success=True, output="t2"),
        rollback_func=rollback_t2,
        reversible=True,
    )

    registry = CapabilityRegistry()
    registry.register_tool(tool1)
    registry.register_tool(tool2)

    state: AgentState = {
        "execution_records": [
            StepExecutionRecord(
                step_id="step-1",
                tool_name="tool_1",
                status=StepStatus.COMPLETED,
                rollback_context={"id": "item_1"},
            ),
            StepExecutionRecord(
                step_id="step-2",
                tool_name="tool_2",
                status=StepStatus.COMPLETED,
                rollback_context={"id": "item_2"},
            ),
        ],
        "errors": [],
        "audit_trail": [],
    }

    result = await rollback_node(state, registry=registry)

    # Debe ejecutarse primero step-2 (tool_2) y después step-1 (tool_1)
    assert call_order == ["rollback_t2_item_2", "rollback_t1_item_1"]
    assert result["status"] == AgentExecutionStatus.FAILED

    records = result["rollback_records"]
    assert len(records) == 2
    assert records[0]["tool_name"] == "tool_2"
    assert records[0]["success"] is True
    assert records[1]["tool_name"] == "tool_1"
    assert records[1]["success"] is True

    audits = result["audit_trail"]
    assert len(audits) == 1
    assert audits[0].event_type == "rollback_completed"
    assert audits[0].details["steps_reverted"] == 2
    assert audits[0].details["succeeded"] == 2

    assert len(result["errors"]) == 1
    assert result["errors"][0].code == "ROLLBACK_TRIGGERED"


@pytest.mark.asyncio
async def test_rollback_node_skips_non_reversible_tools() -> None:
    """Verifica que las herramientas no reversibles no intenten compensarse."""
    tool_norev = AgentTool(
        name="non_reversible_tool",
        description="No compensable",
        category="test",
        func=lambda **kwargs: ToolResult(success=True, output="ok"),
        reversible=False,
    )
    registry = CapabilityRegistry()
    registry.register_tool(tool_norev)

    state: AgentState = {
        "execution_records": [
            StepExecutionRecord(
                step_id="step-1",
                tool_name="non_reversible_tool",
                status=StepStatus.COMPLETED,
                rollback_context=None,
            )
        ],
        "errors": [],
    }

    result = await rollback_node(state, registry=registry)
    assert len(result["rollback_records"]) == 0
    assert result["status"] == AgentExecutionStatus.FAILED


@pytest.mark.asyncio
async def test_rollback_node_fault_tolerance() -> None:
    """Verifica que un fallo en la compensación de un paso no impida compensar los demás."""

    def exploding_rollback(ctx: dict[str, Any]) -> ToolResult:
        raise RuntimeError("Error imprevisto en compensador")

    def ok_rollback(ctx: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output="compensado")

    t_bad = AgentTool(
        name="bad_tool",
        description="Falla en rollback",
        category="test",
        func=lambda **kwargs: ToolResult(success=True, output="ok"),
        rollback_func=exploding_rollback,
        reversible=True,
    )
    t_good = AgentTool(
        name="good_tool",
        description="Compensación ok",
        category="test",
        func=lambda **kwargs: ToolResult(success=True, output="ok"),
        rollback_func=ok_rollback,
        reversible=True,
    )

    registry = CapabilityRegistry()
    registry.register_tool(t_bad)
    registry.register_tool(t_good)

    state: AgentState = {
        "execution_records": [
            StepExecutionRecord(
                step_id="s1",
                tool_name="good_tool",
                status=StepStatus.COMPLETED,
                rollback_context={"k": 1},
            ),
            StepExecutionRecord(
                step_id="s2",
                tool_name="bad_tool",
                status=StepStatus.COMPLETED,
                rollback_context={"k": 2},
            ),
        ]
    }

    result = await rollback_node(state, registry=registry)
    records = result["rollback_records"]
    assert len(records) == 2
    # El primero revertido es s2 (bad_tool) y falló
    assert records[0]["tool_name"] == "bad_tool"
    assert records[0]["success"] is False
    assert "Error imprevisto en compensador" in records[0]["error"]
    # El segundo revertido es s1 (good_tool) y tuvo éxito
    assert records[1]["tool_name"] == "good_tool"
    assert records[1]["success"] is True


def test_route_after_verify() -> None:
    """Valida la bifurcación condicional determinista de route_after_verify."""
    # Verificación exitosa -> evaluate
    state_pass: AgentState = {
        "verification_results": [{"status": "pass"}],
        "execution_records": [],
    }
    assert route_after_verify(state_pass, has_rollback=True) == "evaluate"

    # Verificación fallida con herramienta reversible y has_rollback=True -> rollback
    state_fail_rev: AgentState = {
        "verification_results": [{"status": "fail"}],
        "execution_records": [
            StepExecutionRecord(
                step_id="s1",
                tool_name="t1",
                status=StepStatus.COMPLETED,
                rollback_context={"backup": "v1"},
            )
        ],
    }
    assert route_after_verify(state_fail_rev, has_rollback=True) == "rollback"

    # Verificación fallida pero herramienta sin rollback_context -> evaluate
    state_fail_norev: AgentState = {
        "verification_results": [{"status": "fail"}],
        "execution_records": [
            StepExecutionRecord(
                step_id="s1",
                tool_name="t1",
                status=StepStatus.COMPLETED,
                rollback_context=None,
            )
        ],
    }
    assert route_after_verify(state_fail_norev, has_rollback=True) == "evaluate"

    # Verificación fallida pero has_rollback=False -> evaluate
    assert route_after_verify(state_fail_rev, has_rollback=False) == "evaluate"


# ==========================================================
# 3. Tests de Integración LangGraph con Verificación y Rollback
# ==========================================================


@pytest.mark.asyncio
async def test_langgraph_flow_with_verification_pass() -> None:
    """Verifica el flujo execute -> verify (PASS) -> conclude (RESOLVED)."""
    tool = AgentTool(
        name="safe_action",
        description="Operación normal",
        category="ops",
        func=lambda **kwargs: ToolResult(success=True, output="acción completada"),
    )
    registry = CapabilityRegistry()
    registry.register_tool(tool)
    registry.register_engine(MockPassingVerifier())

    checkpointer = MemorySaver()
    builder = GraphBuilder(registry=registry)
    graph = builder.build(checkpointer=checkpointer)

    thread_id = "test-verify-pass-01"
    run_config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "messages": [HumanMessage(content="Ejecutar safe_action")],
        "request": AgentInput(
            prompt="Ejecutar safe_action",
            thread_id=thread_id,
            execution_id="exec-vpass-01",
        ),
        "audit_trail": [],
    }

    result = await graph.ainvoke(initial_state, run_config)

    assert result.get("status") == AgentExecutionStatus.RESOLVED
    v_results = result.get("verification_results", [])
    assert len(v_results) == 1
    assert v_results[0]["status"] == VerificationStatus.PASS.value
    assert len(result.get("rollback_records", [])) == 0


@pytest.mark.asyncio
async def test_langgraph_flow_with_verification_fail_triggers_rollback() -> None:
    """Verifica el flujo execute -> verify (FAIL) -> rollback (COMPENSADO) -> conclude (FAILED)."""
    rollback_executed = False

    def do_action(**kwargs: Any) -> ToolResult:
        return ToolResult(
            success=True,
            output="recurso aprovisionado",
            rollback_context={"resource_id": "res-999"},
        )

    def do_rollback(ctx: dict[str, Any]) -> ToolResult:
        nonlocal rollback_executed
        rollback_executed = True
        return ToolResult(
            success=True,
            output=f"recurso {ctx.get('resource_id')} destruido",
        )

    tool = AgentTool(
        name="provision_resource",
        description="Aprovisionamiento reversible",
        category="infra",
        func=do_action,
        rollback_func=do_rollback,
        reversible=True,
    )

    registry = CapabilityRegistry()
    registry.register_tool(tool)
    registry.register_engine(MockFailingVerifier())

    checkpointer = MemorySaver()
    builder = GraphBuilder(registry=registry)
    graph = builder.build(checkpointer=checkpointer)

    thread_id = "test-rollback-flow-01"
    run_config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "messages": [HumanMessage(content="Aprovisionar recurso")],
        "request": AgentInput(
            prompt="Aprovisionar recurso",
            thread_id=thread_id,
            execution_id="exec-roll-01",
        ),
        "audit_trail": [],
    }

    result = await graph.ainvoke(initial_state, run_config)

    # Comprobar que rollback_func fue efectivamente disparada por el grafo
    assert rollback_executed is True

    # Estado final debe ser FAILED debido a la anomalía de verificación y compensación
    assert result.get("status") == AgentExecutionStatus.FAILED

    # Comprobar registros de rollback en el estado
    rollback_traces = result.get("rollback_records", [])
    assert len(rollback_traces) == 1
    assert rollback_traces[0]["tool_name"] == "provision_resource"
    assert rollback_traces[0]["success"] is True

    # Comprobar auditoría de rollback
    audits = result.get("audit_trail", [])
    assert any(a.event_type == "verification_failed" for a in audits)
    assert any(a.event_type == "rollback_completed" for a in audits)

    # Comprobar que la respuesta del agente explica la compensación
    output = result.get("output")
    assert output is not None
    assert "rollback" in output.response.lower()
