# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias para contratos de iteración, estado y memoria en LOOP-ISSUE-AGENT-008."""

import pytest
from langchain_core.messages import ToolMessage

from app.core.checkpointer import STATE_ALLOWED_CLASSES
from app.models.io import AgentInput
from app.models.state import (
    AgentState,
    EvaluationRecord,
    ExecutionPlan,
    GoalStatus,
    PlanStep,
    append_reducer,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.execute import execute_node


def test_goal_status_values_and_semantics() -> None:
    """Valida los estados semánticos del enum GoalStatus."""
    assert GoalStatus.SATISFIED.value == "satisfied"
    assert GoalStatus.NEEDS_MORE_INFO.value == "needs_more_info"
    assert GoalStatus.BLOCKED_MISSING_CAPABILITY.value == "blocked_missing_capability"
    assert GoalStatus.FAILED.value == "failed"


def test_evaluation_record_creation_and_serialization() -> None:
    """Valida la creación y serialización JSON de EvaluationRecord."""
    record = EvaluationRecord(
        iteration=2,
        goal_status=GoalStatus.BLOCKED_MISSING_CAPABILITY,
        explanation="Se requiere docker:logs pero no existe en el catálogo registrado.",
        missing_capabilities=["docker:logs"],
        suggested_next_action=None,
    )

    assert record.iteration == 2
    assert record.goal_status == GoalStatus.BLOCKED_MISSING_CAPABILITY
    assert record.missing_capabilities == ["docker:logs"]
    assert "docker:logs" in record.explanation

    data = record.model_dump(mode="json")
    assert data["iteration"] == 2
    assert data["goal_status"] == "blocked_missing_capability"
    assert data["missing_capabilities"] == ["docker:logs"]


def test_evaluation_records_append_reducer() -> None:
    """Valida que append_reducer concatena correctamente instancias de EvaluationRecord."""
    rec1 = EvaluationRecord(
        iteration=1,
        goal_status=GoalStatus.NEEDS_MORE_INFO,
        explanation="Iteración 1 completada, se requiere inspección adicional.",
    )
    rec2 = EvaluationRecord(
        iteration=2,
        goal_status=GoalStatus.SATISFIED,
        explanation="Iteración 2 completada satisfactoriamente.",
    )

    merged = append_reducer([rec1], [rec2])
    assert len(merged) == 2
    assert merged[0].iteration == 1
    assert merged[1].iteration == 2


def test_checkpointer_allowlist_contains_loop_models() -> None:
    """Verifica que GoalStatus y EvaluationRecord estén registrados en STATE_ALLOWED_CLASSES."""
    expected = [
        ("app.models", "GoalStatus"),
        ("app.models.state", "GoalStatus"),
        ("app.models", "EvaluationRecord"),
        ("app.models.state", "EvaluationRecord"),
    ]

    for item in expected:
        assert item in STATE_ALLOWED_CLASSES, f"Falta {item} en STATE_ALLOWED_CLASSES"


@pytest.mark.asyncio
async def test_execute_node_emits_tool_message_for_planned_steps() -> None:
    """Verifica que execute_node genere ToolMessage para la memoria incluso si el paso proviene de un plan."""
    from pydantic import BaseModel

    class DummyArgs(BaseModel):
        target: str = "cluster"

    def dummy_func(target: str = "cluster") -> ToolResult:
        return ToolResult(
            success=True,
            output={"status": "healthy", "target": target},
        )

    tool = AgentTool(
        name="test_tool",
        description="Herramienta de prueba",
        category="testing",
        args_schema=DummyArgs,
        func=dummy_func,
        risk_level=RiskLevel.LOW,
    )

    plan = ExecutionPlan(
        plan_id="plan-test-01",
        goal="Verificar estado de salud del cluster",
        steps=[
            PlanStep(
                step_id="step-1",
                tool_name="test_tool",
                tool_args={"target": "production"},
                description="Ejecutar prueba de paso planificado",
            )
        ],
    )

    from app.core.registry import CapabilityRegistry

    registry = CapabilityRegistry()
    registry.register_tool(tool)

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-test-100",
            thread_id="th-test-100",
            prompt="Verificar estado del cluster",
        ),
        "plan": plan,
        "iteration": 1,
        "max_iterations": 3,
        "evaluation_records": [],
    }

    mutations = await execute_node(state, registry=registry)

    assert "messages" in mutations, "Debe emitirse 'messages' con ToolMessage"
    messages = mutations["messages"]
    assert len(messages) == 1
    tool_msg = messages[0]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "step-1"
    assert tool_msg.name == "test_tool"
    assert "healthy" in str(tool_msg.content)
