# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas de fail-loud y anti-fallback en evaluate, reason y adaptadores LLM."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.llm_openai import _extract_tool_calls_from_choice
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import AgentState, GoalStatus
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.nodes.evaluate import evaluate_node
from app.nodes.evaluate_parser import parse_evaluation_response
from app.nodes.reason_classifier import is_simple_greeting_or_chat_llm
from app.nodes.reason_plan_expander import expand_full_action_plan_with_llm


@pytest.mark.asyncio
async def test_evaluate_node_llm_failure_without_previous_errors() -> None:
    """Verifica que un fallo del LLM evaluador produzca FAILED aun sin errores previos."""
    registry = CapabilityRegistry()
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM 503 Service Unavailable"))

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-fl-1",
            thread_id="th-fl-1",
            prompt="Consulta sin fallos previos",
        ),
        "iteration": 1,
        "errors": [],
    }

    mutations = await evaluate_node(state, registry, llm=mock_llm)

    rec = mutations["evaluation_records"][0]
    assert rec.goal_status == GoalStatus.FAILED
    assert mutations["is_resolved"] is False
    assert "errors" in mutations
    assert mutations["errors"][0].code == "LLM_EVALUATION_FAILED"
    assert mutations["errors"][0].fatal is True


def test_evaluate_parser_unstructured_and_corrupt_json() -> None:
    """Verifica que respuestas no JSON o JSON corrupto resulten en GoalStatus.FAILED."""
    # JSON truncado
    status, _, _, _ = parse_evaluation_response(
        content='{"goal_status": "satisfied", "explanation": "incompleto...',
        errors=[],
        tool_names_available={"dummy"},
    )
    assert status == GoalStatus.FAILED

    # Texto plano sin JSON
    status, _, _, _ = parse_evaluation_response(
        content="Respuesta sin estructura JSON",
        errors=[],
        tool_names_available={"dummy"},
    )
    assert status == GoalStatus.FAILED

    # Estado desconocido
    status, _, _, _ = parse_evaluation_response(
        content=json.dumps({"goal_status": "estado_inventado_xyz"}),
        errors=[],
        tool_names_available={"dummy"},
    )
    assert status == GoalStatus.FAILED


def test_extract_tool_calls_corrupt_json_raises_value_error() -> None:
    """Verifica que argumentos de tool_calls con JSON corrupto lancen ValueError."""
    choice = {
        "tool_calls": [
            {
                "id": "tc-1",
                "function": {
                    "name": "deploy_service",
                    "arguments": '{"service": "auth", "replicas": ',  # Truncado
                },
            }
        ]
    }
    with pytest.raises(ValueError, match="JSON corrupto o truncado en tool_call 'deploy_service'"):
        _extract_tool_calls_from_choice(choice)


@pytest.mark.asyncio
async def test_reason_classifier_propagates_llm_exception() -> None:
    """Verifica que las excepciones de inferencia en clasificación no sean silenciadas."""
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("Fallo de red en inferencia"))

    with pytest.raises(RuntimeError, match="Fallo de red en inferencia"):
        await is_simple_greeting_or_chat_llm(mock_llm, "crea un contenedor nuevo")


@pytest.mark.asyncio
async def test_reason_plan_expander_propagates_llm_exception() -> None:
    """Verifica que un fallo del LLM en expansión de plan HITL se propague."""
    registry = CapabilityRegistry()
    registry.register_tool(
        AgentTool(
            name="docker:restart",
            description="Reiniciar contenedor",
            func=lambda: ToolResult(success=True),
            risk_level=RiskLevel.HIGH,
            read_only=False,
        )
    )

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("Fallo en expansor HITL"))

    initial_calls = [
        {
            "id": "call-1",
            "name": "docker:restart",
            "args": {"container_id": "c1"},
            "type": "tool_call",
        }
    ]

    with pytest.raises(RuntimeError, match="Fallo en expansor HITL"):
        await expand_full_action_plan_with_llm(
            model=mock_llm,
            prompt="reinicia el contenedor c1",
            initial_tool_calls=initial_calls,
            registry=registry,
        )
