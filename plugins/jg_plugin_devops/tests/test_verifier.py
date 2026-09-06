"""Tests unitarios y de integración para DevopsVerifierEngine de jg_plugin_devops."""

import pytest

from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentState,
    ExecutionError,
    ExecutionPlan,
    PlanStep,
    StepExecutionRecord,
    StepStatus,
    VerificationStatus,
)
from app.models.tools import RiskLevel
from app.nodes.verify import verify_node
from app.plugins.base import VerifierEngine
from jg_plugin_devops.verifier import DevopsVerifierEngine


def test_verifier_contract_and_metadata() -> None:
    """Valida el contrato formal de VerifierEngine y metadatos del verificador DevOps."""
    verifier = DevopsVerifierEngine()
    assert isinstance(verifier, VerifierEngine)
    assert verifier.name == "devops_verifier"
    assert verifier.engine_type == "verifier"


@pytest.mark.asyncio
async def test_verifier_lifecycle() -> None:
    """Valida los hooks de ciclo de vida del verificador."""
    verifier = DevopsVerifierEngine()
    assert verifier._is_started is False

    await verifier.startup()
    assert verifier._is_started is True

    await verifier.shutdown()
    assert verifier._is_started is False


@pytest.mark.asyncio
async def test_verify_successful_resolution() -> None:
    """Valida que verify() confirma la resolución cuando los pasos se completaron sin fallos."""
    verifier = DevopsVerifierEngine()

    plan = ExecutionPlan(
        plan_id="plan-test",
        goal="Reiniciar contenedor web_api",
        steps=[
            PlanStep(
                step_id="step-1",
                tool_name="restart_container",
                tool_args={"title": "web_api"},
                description="Reiniciar contenedor",
                risk_level=RiskLevel.HIGH,
            )
        ],
    )

    records = [
        StepExecutionRecord(
            step_id="step-1",
            tool_name="restart_container",
            tool_args={"title": "web_api"},
            status=StepStatus.COMPLETED,
            output="Contenedor web_api reiniciado",
            duration_ms=120.0,
        )
    ]

    state = AgentState(
        request=AgentInput(
            execution_id="exec-v-1",
            thread_id="thread-v-1",
            prompt="Reiniciar web_api",
        ),
        plan=plan,
        execution_records=records,
        errors=[],
    )

    result = await verifier.verify(state)

    assert result["status"] == VerificationStatus.PASS
    assert result["resolved"] is True
    assert result["verified_by"] == "devops_verifier"
    assert "web_api" in result["service"]
    assert any(c["name"] == "service_health_check" and c["passed"] for c in result["checks"])


@pytest.mark.asyncio
async def test_verify_failed_steps() -> None:
    """Valida que verify() detecta fallos cuando un paso de ejecución no fue exitoso."""
    verifier = DevopsVerifierEngine()

    records = [
        StepExecutionRecord(
            step_id="step-1",
            tool_name="restart_container",
            tool_args={},
            status=StepStatus.FAILED,
            error="Connection refused to docker daemon",
            duration_ms=50.0,
        )
    ]

    state = AgentState(
        request=AgentInput(
            execution_id="exec-v-2",
            thread_id="thread-v-2",
            prompt="Reiniciar servicio",
        ),
        execution_records=records,
        errors=[],
    )

    result = await verifier.verify(state)

    assert result["status"] == VerificationStatus.FAIL
    assert result["resolved"] is False
    assert "step-1" in result["failed_steps"]


@pytest.mark.asyncio
async def test_verify_fatal_errors() -> None:
    """Valida que verify() falla ante errores operacionales fatales."""
    verifier = DevopsVerifierEngine()

    state = AgentState(
        request=AgentInput(
            execution_id="exec-v-3",
            thread_id="thread-v-3",
            prompt="Operación crítica",
        ),
        execution_records=[],
        errors=[
            ExecutionError(
                code="FATAL_CRASH",
                message="Docker daemon unreachable",
                component="docker",
                fatal=True,
            )
        ],
    )

    result = await verifier.verify(state)

    assert result["status"] == VerificationStatus.FAIL
    assert result["resolved"] is False


@pytest.mark.asyncio
async def test_verify_degraded_state() -> None:
    """Valida que verify() marca estado DEGRADED ante errores no fatales."""
    verifier = DevopsVerifierEngine()

    records = [
        StepExecutionRecord(
            step_id="step-1",
            tool_name="inspect_service",
            tool_args={},
            status=StepStatus.COMPLETED,
            output="ok",
        )
    ]

    state = AgentState(
        request=AgentInput(
            execution_id="exec-v-4",
            thread_id="thread-v-4",
            prompt="Comprobar servicio",
        ),
        execution_records=records,
        errors=[
            ExecutionError(
                code="WARNING_HIGH_MEM",
                message="Memoria al 88%",
                component="host",
                fatal=False,
            )
        ],
    )

    result = await verifier.verify(state)

    assert result["status"] == VerificationStatus.DEGRADED
    assert result["resolved"] is False


@pytest.mark.asyncio
async def test_integration_with_verify_node() -> None:
    """Valida la integración completa de DevopsVerifierEngine con el nodo verify de LangGraph."""
    verifier = DevopsVerifierEngine()
    registry = CapabilityRegistry()
    registry.register_engine(verifier)

    assert registry.get_verifier() is verifier

    records = [
        StepExecutionRecord(
            step_id="step-1",
            tool_name="inspect_resource_usage",
            tool_args={},
            status=StepStatus.COMPLETED,
            output="Métricas inspeccionadas",
        )
    ]

    state = AgentState(
        request=AgentInput(
            execution_id="exec-node-v",
            thread_id="thread-node-v",
            prompt="Auditar métricas",
        ),
        execution_records=records,
        errors=[],
    )

    updates = await verify_node(state, registry=registry)

    assert "verification_results" in updates
    results = updates["verification_results"]
    assert len(results) >= 1
    v_res = results[0]
    assert v_res["status"] == VerificationStatus.PASS.value
    assert v_res["details"]["verified_by"] == "devops_verifier"

    audit_trail = updates.get("audit_trail", [])
    assert len(audit_trail) == 1
    assert audit_trail[0].event_type == "verification_completed"
    assert audit_trail[0].actor == "devops_verifier"
