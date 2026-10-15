# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias e integradas para el nodo opcional de planificación (plan_node).

Verifica la invocación polimórfica de PlannerEngine (sync y async), la generación de
ExecutionPlan con pasos y dependencias, la propagación de niveles de riesgo, la tolerancia
a fallos y la integración en el ciclo cognitivo completo de LangGraph.
"""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.graph import GraphBuilder
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ExecutionPlan,
    IntentModel,
    PlanStep,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.plan import plan_node
from app.plugins.base import PlannerEngine

# ==========================================================
# Motores de Planificación Mock para Pruebas
# ==========================================================


class AsyncMockPlanner(PlannerEngine):
    """PlannerEngine con formulación asíncrona de planes y dependencias explícitas."""

    @property
    def name(self) -> str:
        return "async_mock_planner"

    async def create_plan(self, state: AgentState) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id="plan-async-01",
            goal="Diagnosticar y reparar pod caído",
            steps=[
                PlanStep(
                    step_id="step-1",
                    tool_name="diag_tool",
                    tool_args={"target": "pod-alpha"},
                    description="Paso inicial de inspección",
                    risk_level=RiskLevel.LOW,
                    reversible=True,
                    dependencies=[],
                ),
                PlanStep(
                    step_id="step-2",
                    tool_name="restart_tool",
                    tool_args={"target": "pod-alpha"},
                    description="Reinicio condicional",
                    risk_level=RiskLevel.MEDIUM,
                    reversible=False,
                    dependencies=["step-1"],
                ),
            ],
            estimated_risk=RiskLevel.MEDIUM,
        )


class SyncMockPlanner(PlannerEngine):
    """PlannerEngine con formulación síncrona."""

    @property
    def name(self) -> str:
        return "sync_mock_planner"

    def plan(self, state: AgentState) -> ExecutionPlan:
        return ExecutionPlan(
            plan_id="plan-sync-01",
            goal="Optimización síncrona",
            steps=[
                PlanStep(
                    step_id="step-s1",
                    tool_name="sync_tool",
                    tool_args={},
                    risk_level=RiskLevel.LOW,
                    dependencies=[],
                )
            ],
            estimated_risk=RiskLevel.LOW,
        )


class DictReturningPlanner(PlannerEngine):
    """PlannerEngine que retorna un diccionario plano en lugar de ExecutionPlan."""

    @property
    def name(self) -> str:
        return "dict_returning_planner"

    async def build_plan(self) -> dict[str, Any]:
        return {
            "plan_id": "plan-dict-01",
            "goal": "Operación desde diccionario",
            "steps": [
                {
                    "step_id": "step-d1",
                    "tool_name": "raw_tool",
                    "tool_args": {"mode": "fast"},
                    "risk_level": "high",
                    "dependencies": ["step-init"],
                }
            ],
            "estimated_risk": "high",
        }


class ListStepsPlanner(PlannerEngine):
    """PlannerEngine que retorna una lista de pasos en generate_plan()."""

    @property
    def name(self) -> str:
        return "list_steps_planner"

    def generate_plan(self, state: AgentState) -> list[PlanStep]:
        return [
            PlanStep(
                step_id="step-l1",
                tool_name="first_step",
                dependencies=[],
            ),
            PlanStep(
                step_id="step-l2",
                tool_name="second_step",
                dependencies=["step-l1"],
            ),
        ]


class FailingPlanner(PlannerEngine):
    """PlannerEngine que lanza una excepción en tiempo de ejecución."""

    @property
    def name(self) -> str:
        return "failing_planner"

    async def create_plan(self, state: AgentState) -> ExecutionPlan:
        raise TimeoutError("Fallo de conexión con el proveedor de planificación cognitiva")


def dummy_tool_func(**kwargs: Any) -> ToolResult:
    return ToolResult(success=True, output="ok")


# ==========================================================
# Tests Unitarios para plan_node
# ==========================================================


@pytest.mark.asyncio
async def test_plan_node_with_async_planner() -> None:
    """Verifica que plan_node ejecute un PlannerEngine asíncrono y conserve pasos y dependencias."""
    registry = CapabilityRegistry()
    engine = AsyncMockPlanner()
    registry.register_engine(engine)

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-01",
            thread_id="thread-plan-01",
            prompt="Reparar pod",
        ),
        "messages": [HumanMessage(content="Reparar pod")],
        "status": AgentExecutionStatus.IDLE,
    }

    result = await plan_node(state, registry=registry)

    assert result["status"] == AgentExecutionStatus.PLANNING
    plan = result["plan"]
    assert isinstance(plan, ExecutionPlan)
    assert plan.plan_id == "plan-async-01"
    assert len(plan.steps) == 2
    assert plan.steps[0].step_id == "step-1"
    assert plan.steps[1].dependencies == ["step-1"]
    assert plan.estimated_risk == RiskLevel.MEDIUM

    assert len(result["audit_trail"]) == 1
    audit = result["audit_trail"][0]
    assert audit.event_type == "planning_completed"
    assert audit.actor == "async_mock_planner"
    assert audit.details["steps_count"] == 2
    assert audit.details["duration_ms"] >= 0.0


@pytest.mark.asyncio
async def test_plan_node_with_sync_planner() -> None:
    """Verifica soporte para motores de planificación con métodos síncronos."""
    engine = SyncMockPlanner()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-02",
            thread_id="thread-plan-02",
            prompt="Optimizar",
        ),
        "messages": [],
    }

    result = await plan_node(state, engine=engine)

    assert result["status"] == AgentExecutionStatus.PLANNING
    assert result["plan"].plan_id == "plan-sync-01"
    assert len(result["plan"].steps) == 1
    assert result["audit_trail"][0].actor == "sync_mock_planner"


@pytest.mark.asyncio
async def test_plan_node_converts_dict_plan() -> None:
    """Verifica que un diccionario retornado por un motor sea transformado a ExecutionPlan."""
    engine = DictReturningPlanner()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-03",
            thread_id="thread-plan-03",
            prompt="Ejecutar dict plan",
        ),
        "messages": [],
    }

    result = await plan_node(state, engine=engine)

    plan = result["plan"]
    assert isinstance(plan, ExecutionPlan)
    assert plan.plan_id == "plan-dict-01"
    assert plan.steps[0].dependencies == ["step-init"]
    assert plan.estimated_risk == RiskLevel.HIGH


@pytest.mark.asyncio
async def test_plan_node_converts_list_of_steps() -> None:
    """Verifica que una lista de PlanStep sea unificada en un ExecutionPlan con goal del intent."""
    engine = ListStepsPlanner()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-04",
            thread_id="thread-plan-04",
            prompt="Lista de pasos",
        ),
        "intent": IntentModel(goal="Secuencia de dos pasos", action_type="plan"),
        "messages": [],
    }

    result = await plan_node(state, engine=engine)

    plan = result["plan"]
    assert isinstance(plan, ExecutionPlan)
    assert plan.goal == "Secuencia de dos pasos"
    assert len(plan.steps) == 2
    assert plan.steps[1].dependencies == ["step-l1"]


@pytest.mark.asyncio
async def test_plan_node_without_planner_fails_safe_without_arbitrary_tools() -> None:
    """Verifica contención segura: ante ausencia de plan estructurado, NO se ejecuta una herramienta arbitraria (AGENTE-LOGIC-02)."""
    registry = CapabilityRegistry()
    tool = AgentTool(
        name="fallback_tool",
        description="Herramienta de reserva no solicitada",
        category="core",
        func=dummy_tool_func,
        risk_level=RiskLevel.MEDIUM,
    )
    registry.register_tool(tool)

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-05",
            thread_id="thread-plan-05",
            prompt="Ejecución sin plan",
        ),
        "intent": IntentModel(goal="Objetivo sin plan", action_type="plan"),
        "messages": [],
    }

    result = await plan_node(state, registry=registry)

    # Debe fallar de forma segura sin pasos arbitrarios
    assert result["status"] == AgentExecutionStatus.FAILED
    plan = result["plan"]
    assert isinstance(plan, ExecutionPlan)
    assert plan.goal == "Objetivo sin plan"
    assert len(plan.steps) == 0
    assert "errors" in result
    assert any(e.code == "PLANNING_FAILED" and e.fatal is True for e in result["errors"])
    assert result["cognitive_steps"][0].status == "failed"


@pytest.mark.asyncio
async def test_plan_node_computes_estimated_risk() -> None:
    """Verifica que el estimated_risk del plan sea promovido al máximo riesgo de los pasos."""

    class HighRiskStepPlanner(PlannerEngine):
        @property
        def name(self) -> str:
            return "high_risk_step_planner"

        def plan(self) -> ExecutionPlan:
            return ExecutionPlan(
                plan_id="plan-risk-calc",
                goal="Operación crítica",
                steps=[
                    PlanStep(step_id="s1", tool_name="safe", risk_level=RiskLevel.LOW),
                    PlanStep(step_id="s2", tool_name="nuke", risk_level=RiskLevel.CRITICAL),
                ],
                estimated_risk=RiskLevel.LOW,  # Forzar inicial bajo para verificar recálculo
            )

    engine = HighRiskStepPlanner()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-06",
            thread_id="thread-plan-06",
            prompt="Test riesgo",
        ),
        "messages": [],
    }

    result = await plan_node(state, engine=engine)

    assert result["plan"].estimated_risk == RiskLevel.CRITICAL


@pytest.mark.asyncio
async def test_plan_node_captures_engine_exception() -> None:
    """Verifica que excepciones del motor se contengan en ExecutionError y marquen fallo sin herramientas aleatorias."""
    engine = FailingPlanner()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-07",
            thread_id="thread-plan-07",
            prompt="Plan con fallo",
        ),
        "messages": [],
        "errors": [],
    }

    result = await plan_node(state, engine=engine)

    assert result["status"] == AgentExecutionStatus.FAILED
    assert "errors" in result
    assert len(result["errors"]) >= 1
    err_codes = [e.code for e in result["errors"]]
    assert "PLANNER_EXECUTION_ERROR" in err_codes
    assert "PLANNING_FAILED" in err_codes

    assert result["audit_trail"][0].details["has_errors"] is True
    assert result["audit_trail"][0].details["is_failed"] is True
    assert len(result["plan"].steps) == 0


# ==========================================================
# Test de Integración con Grafo LangGraph Compilado
# ==========================================================


@pytest.mark.asyncio
async def test_plan_node_graph_integration() -> None:
    """Verifica la ejecución del nodo plan dentro de un grafo LangGraph compilado."""
    registry = CapabilityRegistry()
    registry.register_engine(AsyncMockPlanner())

    diag_tool = AgentTool(
        name="diag_tool",
        description="Diagnóstico",
        category="devops",
        func=dummy_tool_func,
        risk_level=RiskLevel.LOW,
    )
    restart_tool = AgentTool(
        name="restart_tool",
        description="Reinicio",
        category="devops",
        func=dummy_tool_func,
        risk_level=RiskLevel.MEDIUM,
    )
    registry.register_tool(diag_tool)
    registry.register_tool(restart_tool)

    builder = GraphBuilder(registry)
    topology = builder.get_topology()
    assert topology.has_planner is True
    assert "plan" in topology.nodes

    graph = builder.build()
    config: RunnableConfig = {"configurable": {"thread_id": "thread-plan-graph-01"}}

    initial_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-graph-01",
            thread_id="thread-plan-graph-01",
            prompt="Reparar pod caído en producción",
        ),
        "messages": [HumanMessage(content="Reparar pod caído en producción")],
        "status": AgentExecutionStatus.IDLE,
    }

    result = await graph.ainvoke(initial_state, config=config)

    assert result["status"] == AgentExecutionStatus.RESOLVED
    assert result.get("plan") is not None
    plan = result["plan"]
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) == 2
    # El paso 2 debe tener la dependencia preservada
    assert plan.steps[1].dependencies == ["step-1"]
    # Los pasos deben haber sido ejecutados
    assert len(result["execution_records"]) == 2
    assert result.get("output") is not None
    assert result["output"].status.value in ("completed", "resolved")


@pytest.mark.asyncio
async def test_plan_node_failure_routes_to_conclude_without_executing_tools() -> None:
    """Verifica en grafo LangGraph compilado que una falla de planificación deriva a conclude sin ejecutar herramientas."""
    registry = CapabilityRegistry()
    registry.register_engine(FailingPlanner())

    executed_tools: list[str] = []

    def spy_tool_func(**kwargs: Any) -> ToolResult:
        executed_tools.append("spy_tool")
        return ToolResult(success=True, output="executed")

    tool = AgentTool(
        name="arbitrary_tool",
        description="Herramienta en el registro",
        category="devops",
        func=spy_tool_func,
        risk_level=RiskLevel.LOW,
    )
    registry.register_tool(tool)

    builder = GraphBuilder(registry)
    graph = builder.build()
    config: RunnableConfig = {"configurable": {"thread_id": "thread-plan-fail-01"}}

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-plan-fail-01",
            thread_id="thread-plan-fail-01",
            prompt="Ejecutar con planificador fallido",
        ),
        "intent": IntentModel(goal="Objetivo con fallo de planner", action_type="plan"),
        "messages": [HumanMessage(content="Ejecutar con planificador fallido")],
        "status": AgentExecutionStatus.IDLE,
    }

    result = await graph.ainvoke(state, config=config)

    assert result["status"] == AgentExecutionStatus.FAILED
    assert result["is_resolved"] is False
    # Ninguna herramienta debe haber sido ejecutada
    assert len(executed_tools) == 0
    assert len(result.get("execution_records") or []) == 0
    # La salida final debe indicar fallo
    assert result.get("output") is not None
    assert result["output"].status.value in ("failed", "cancelled")
    assert (
        "error" in result["output"].response.lower() or "falló" in result["output"].response.lower()
    )
