# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias para el nodo de evaluación semántica y capability-awareness (evaluate_node)."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage

from app.core.llm import MockChatModel
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentState,
    CognitiveStepRecord,
    EvaluationRecord,
    ExecutionError,
    GoalStatus,
    StepExecutionRecord,
    StepStatus,
)
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.evaluate import evaluate_node


def _create_registry_with_docker_tools() -> CapabilityRegistry:
    """Crea un registry con herramientas básicas simuladas (sin docker:logs)."""
    registry = CapabilityRegistry()

    def dummy_list() -> ToolResult:
        return ToolResult(
            success=True, output=["container-1 (restarting)", "container-2 (running)"]
        )

    def dummy_inspect(container_id: str) -> ToolResult:
        return ToolResult(success=True, output={"id": container_id, "state": "restarting"})

    from pydantic import BaseModel

    class EmptyArgs(BaseModel):
        pass

    class InspectArgs(BaseModel):
        container_id: str

    registry.register_tool(
        AgentTool(
            name="docker:list",
            description="Listar contenedores",
            category="docker",
            args_schema=EmptyArgs,
            func=dummy_list,
            risk_level=RiskLevel.LOW,
        )
    )
    registry.register_tool(
        AgentTool(
            name="docker:inspect",
            description="Inspeccionar contenedor",
            category="docker",
            args_schema=InspectArgs,
            func=dummy_inspect,
            risk_level=RiskLevel.LOW,
        )
    )
    return registry


@pytest.mark.asyncio
async def test_evaluate_node_satisfied() -> None:
    """Valida evaluación positiva cuando la evidencia resuelve el objetivo."""
    registry = _create_registry_with_docker_tools()

    llm_payload: dict[str, Any] = {
        "goal_status": "satisfied",
        "explanation": "Se listaron los contenedores correctamente y no hay más acciones requeridas.",
        "missing_capabilities": [],
        "suggested_next_action": None,
    }
    mock_llm = MockChatModel(response_content=json.dumps(llm_payload))

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-eval-1",
            thread_id="th-eval-1",
            prompt="¿Qué contenedores están corriendo?",
        ),
        "iteration": 1,
        "execution_records": [
            StepExecutionRecord(
                step_id="step-1",
                tool_name="docker:list",
                status=StepStatus.COMPLETED,
                output=["container-2 (running)"],
            )
        ],
        "messages": [
            ToolMessage(
                content="['container-2 (running)']", tool_call_id="call-1", name="docker:list"
            )
        ],
    }

    mutations = await evaluate_node(state, registry, llm=mock_llm)

    assert "evaluation_records" in mutations
    eval_records = mutations["evaluation_records"]
    assert len(eval_records) == 1
    rec: EvaluationRecord = eval_records[0]
    assert rec.goal_status == GoalStatus.SATISFIED
    assert rec.iteration == 1
    assert "correctamente" in rec.explanation
    assert mutations["is_resolved"] is True

    # Comprobar traza cognitiva para la consola web
    assert "cognitive_steps" in mutations
    cog_step: CognitiveStepRecord = mutations["cognitive_steps"][0]
    assert cog_step.node == "evaluate"
    assert "SATISFIED" in cog_step.action


@pytest.mark.asyncio
async def test_evaluate_node_needs_more_info() -> None:
    """Valida que el evaluador identifique la necesidad de ejecutar otra herramienta registrada."""
    registry = _create_registry_with_docker_tools()

    llm_payload = {
        "goal_status": "needs_more_info",
        "explanation": "Se detectó el contenedor container-1 reiniciándose; se debe inspeccionar sus metadatos.",
        "missing_capabilities": [],
        "suggested_next_action": "docker:inspect",
    }
    mock_llm = MockChatModel(response_content=json.dumps(llm_payload))

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-eval-2",
            thread_id="th-eval-2",
            prompt="Revisa el contenedor que falla",
        ),
        "iteration": 1,
        "execution_records": [],
    }

    mutations = await evaluate_node(state, registry, llm=mock_llm)

    rec: EvaluationRecord = mutations["evaluation_records"][0]
    assert rec.goal_status == GoalStatus.NEEDS_MORE_INFO
    assert rec.suggested_next_action == "docker:inspect"
    assert mutations["is_resolved"] is False


@pytest.mark.asyncio
async def test_evaluate_node_blocked_missing_capability() -> None:
    """Valida la detección de capability ausente (Capability-Awareness) ante falta de docker:logs."""
    registry = _create_registry_with_docker_tools()

    llm_payload = {
        "goal_status": "blocked_missing_capability",
        "explanation": (
            "El contenedor 'app-service' se encuentra en bucle CrashLoopBackOff. Para identificar el "
            "error exacto del proceso se requiere consultar los logs del contenedor ('docker:logs'), "
            "pero esta capacidad no está disponible en el catálogo del agente."
        ),
        "missing_capabilities": ["docker:logs"],
        "suggested_next_action": None,
    }
    mock_llm = MockChatModel(response_content=json.dumps(llm_payload))

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-eval-3",
            thread_id="th-eval-3",
            prompt="Diagnostica por qué reinicia app-service",
        ),
        "iteration": 1,
        "execution_records": [
            StepExecutionRecord(
                step_id="step-1",
                tool_name="docker:inspect",
                status=StepStatus.COMPLETED,
                output={"state": "restarting", "exit_code": 137},
            )
        ],
    }

    mutations = await evaluate_node(state, registry, llm=mock_llm)

    rec: EvaluationRecord = mutations["evaluation_records"][0]
    assert rec.goal_status == GoalStatus.BLOCKED_MISSING_CAPABILITY
    assert "docker:logs" in rec.missing_capabilities
    assert "CrashLoopBackOff" in rec.explanation
    assert mutations["is_resolved"] is False


@pytest.mark.asyncio
async def test_evaluate_node_auto_corrects_unregistered_suggested_tool() -> None:
    """Valida auto-corrección a BLOCKED_MISSING_CAPABILITY si el LLM sugiere una tool inexistente."""
    registry = _create_registry_with_docker_tools()

    # El LLM erróneamente marcó needs_more_info sugiriendo una herramienta que NO existe
    llm_payload = {
        "goal_status": "needs_more_info",
        "explanation": "Se necesitan logs para continuar.",
        "missing_capabilities": [],
        "suggested_next_action": "docker:logs",
    }
    mock_llm = MockChatModel(response_content=json.dumps(llm_payload))

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-eval-4",
            thread_id="th-eval-4",
            prompt="Dame los logs",
        ),
        "iteration": 1,
    }

    mutations = await evaluate_node(state, registry, llm=mock_llm)

    rec: EvaluationRecord = mutations["evaluation_records"][0]
    # El nodo debió auto-corregir el estado porque docker:logs no existe en available_tools
    assert rec.goal_status == GoalStatus.BLOCKED_MISSING_CAPABILITY
    assert "docker:logs" in rec.missing_capabilities


@pytest.mark.asyncio
async def test_evaluate_node_markdown_json_cleaning() -> None:
    """Valida que los delimitadores markdown ```json ... ``` sean limpiados correctamente."""
    registry = _create_registry_with_docker_tools()

    markdown_content = """Aquí está la evaluación solicitada:
```json
{
  "goal_status": "satisfied",
  "explanation": "Objetivo cumplido.",
  "missing_capabilities": [],
  "suggested_next_action": null
}
```
Fin de la evaluación."""
    mock_llm = MockChatModel(response_content=markdown_content)

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-eval-5",
            thread_id="th-eval-5",
            prompt="Consulta simple",
        ),
        "iteration": 1,
    }

    mutations = await evaluate_node(state, registry, llm=mock_llm)
    rec: EvaluationRecord = mutations["evaluation_records"][0]
    assert rec.goal_status == GoalStatus.SATISFIED
    assert rec.explanation == "Objetivo cumplido."


@pytest.mark.asyncio
async def test_evaluate_node_fallback_on_exception() -> None:
    """Valida que si el LLM falla, el nodo aplica un fallback defensivo sin hacer crash."""
    registry = _create_registry_with_docker_tools()

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("API Gateway Timeout simulado"))

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-eval-6",
            thread_id="th-eval-6",
            prompt="Consulta con fallo",
        ),
        "iteration": 1,
        "errors": [
            ExecutionError(
                code="CRITICAL_FAIL", message="Fallo grave en herramienta", component="tool"
            )
        ],
    }

    mutations = await evaluate_node(state, registry, llm=mock_llm)

    rec: EvaluationRecord = mutations["evaluation_records"][0]
    assert rec.goal_status == GoalStatus.FAILED
    assert "API Gateway Timeout simulado" in rec.explanation
    assert mutations["is_resolved"] is False
    assert mutations["errors"][0].code == "LLM_EVALUATION_FAILED"
