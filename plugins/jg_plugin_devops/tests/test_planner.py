"""Tests unitarios y de integración para DAGPlannerEngine de jg_plugin_devops."""

import pytest

from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ExecutionPlan,
    IntentModel,
)
from app.models.tools import RiskLevel
from app.nodes.plan import plan_node
from app.plugins.base import PlannerEngine
from jg_plugin_devops.models.snapshot import (
    IncidentSeverity,
    InfraIncident,
)
from jg_plugin_devops.planner import DAGPlannerEngine


def test_planner_contract_and_metadata() -> None:
    """Valida el contrato formal de PlannerEngine y metadatos del planificador DAG."""
    planner = DAGPlannerEngine()
    assert isinstance(planner, PlannerEngine)
    assert planner.name == "dag_planner"
    assert planner.engine_type == "planner"


@pytest.mark.asyncio
async def test_planner_lifecycle() -> None:
    """Valida los hooks de ciclo de vida del planificador."""
    planner = DAGPlannerEngine()
    assert planner._is_started is False

    await planner.startup()
    assert planner._is_started is True

    await planner.shutdown()
    assert planner._is_started is False


def test_plan_from_incidents_dag_structure() -> None:
    """Valida la formulación de DAGs ordenados ante incidentes detectados de infraestructura."""
    planner = DAGPlannerEngine()

    incidents = [
        InfraIncident(
            severity=IncidentSeverity.HIGH,
            title="Contenedor unhealthy: payments_api",
            component="docker",
        ).model_dump(),
        InfraIncident(
            severity=IncidentSeverity.HIGH,
            title="Uso de CPU crítico en el Host",
            component="host",
        ).model_dump(),
    ]

    state = AgentState(
        request=AgentInput(
            execution_id="exec-plan-01",
            thread_id="thread-plan-01",
            prompt="Remediar incidentes activos",
        ),
        environment_snapshot={"incidents": incidents},
    )

    plan = planner.create_plan(state)

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) == 6  # 3 pasos para docker + 3 pasos para host
    assert plan.estimated_risk == RiskLevel.HIGH

    # Verificar DAG y dependencias
    step_ids = [s.step_id for s in plan.steps]
    for step in plan.steps:
        for dep in step.dependencies:
            assert dep in step_ids
            # La dependencia debe haberse declarado antes que el paso actual
            assert step_ids.index(dep) < step_ids.index(step.step_id)

    # Verificar niveles de riesgo
    docker_remed = next(s for s in plan.steps if s.tool_name == "restart_container")
    assert docker_remed.risk_level == RiskLevel.HIGH
    assert docker_remed.reversible is True

    host_diag = next(s for s in plan.steps if s.tool_name == "inspect_resource_usage")
    assert host_diag.risk_level == RiskLevel.LOW


def test_plan_risk_levels_from_prompts() -> None:
    """Valida la correcta clasificación de niveles de riesgo a partir de la intención del prompt."""
    planner = DAGPlannerEngine()

    # 1. Operación destructiva -> CRITICAL
    state_crit = AgentState(
        request=AgentInput(
            execution_id="exec-crit",
            thread_id="thread-crit",
            prompt="Eliminar volumen antiguo de base de datos",
        )
    )
    plan_crit = planner.create_plan(state_crit)
    assert plan_crit.estimated_risk == RiskLevel.CRITICAL
    assert any(s.risk_level == RiskLevel.CRITICAL for s in plan_crit.steps)

    # 2. Operación de mutación/reinicio -> HIGH
    state_high = AgentState(
        request=AgentInput(
            execution_id="exec-high",
            thread_id="thread-high",
            prompt="Reiniciar servicio nginx en servidor de producción",
        )
    )
    plan_high = planner.create_plan(state_high)
    assert plan_high.estimated_risk == RiskLevel.HIGH
    assert any(s.risk_level == RiskLevel.HIGH for s in plan_high.steps)

    # 3. Operación preventiva/recarga -> MEDIUM
    state_med = AgentState(
        request=AgentInput(
            execution_id="exec-med",
            thread_id="thread-med",
            prompt="Recargar configuración de proxy inverso",
        )
    )
    plan_med = planner.create_plan(state_med)
    assert plan_med.estimated_risk == RiskLevel.MEDIUM

    # 4. Operación de sólo lectura -> LOW
    state_low = AgentState(
        request=AgentInput(
            execution_id="exec-low",
            thread_id="thread-low",
            prompt="Consultar estado de memoria y telemetría",
        )
    )
    plan_low = planner.create_plan(state_low)
    assert plan_low.estimated_risk == RiskLevel.LOW


@pytest.mark.asyncio
async def test_integration_with_plan_node() -> None:
    """Valida la integración directa de DAGPlannerEngine con el nodo plan de LangGraph."""
    planner = DAGPlannerEngine()
    registry = CapabilityRegistry()
    registry.register_engine(planner)

    assert registry.get_planner() is planner

    state = AgentState(
        request=AgentInput(
            execution_id="exec-node-plan",
            thread_id="thread-node-plan",
            prompt="Reiniciar contenedor Redis ante alta latencia",
        ),
        intent=IntentModel(goal="Restablecer servicio de caché Redis"),
    )

    updates = await plan_node(state, registry=registry)

    assert updates["status"] == AgentExecutionStatus.PLANNING
    assert "plan" in updates
    plan = updates["plan"]
    assert isinstance(plan, ExecutionPlan)
    assert plan.estimated_risk == RiskLevel.HIGH
    assert len(plan.steps) >= 2

    # Validar traza inmutable de auditoría
    audit_trail = updates.get("audit_trail", [])
    assert len(audit_trail) == 1
    record = audit_trail[0]
    assert record.event_type == "planning_completed"
    assert record.actor == "dag_planner"
    assert record.details["estimated_risk"] == "high"
