# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios y de integración para la topología cíclica y guardarraíles (LOOP-ISSUE-AGENT-010)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.core.graph import (
    GraphBuilder,
    route_after_evaluation,
    route_after_execute,
    route_after_verify,
)
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentState,
    EvaluationRecord,
    GoalStatus,
    StepExecutionRecord,
    StepStatus,
)
from app.nodes.conclude import conclude_node
from app.nodes.reason import reason_node


def test_topology_includes_evaluate() -> None:
    """Verifica que la topología incluya el nodo 'evaluate' y que has_evaluator sea True."""
    registry = CapabilityRegistry()
    builder = GraphBuilder(registry)
    topo = builder.get_topology()

    assert topo.has_evaluator is True
    assert "evaluate" in topo.nodes
    assert "conclude" in topo.nodes
    # 'evaluate' precede a 'conclude'
    assert topo.nodes.index("evaluate") < topo.nodes.index("conclude")


def test_route_after_execute_and_verify() -> None:
    """Verifica el enrutamiento desde execute y verify hacia evaluate."""
    state: AgentState = {"status": "running"}

    # Sin verifier, execute va a evaluate
    assert route_after_execute(state, has_verifier=False) == "evaluate"
    # Con verifier, execute va a verify
    assert route_after_execute(state, has_verifier=True) == "verify"

    # Verify sin fallos va a evaluate
    state["verification_results"] = [{"status": "pass", "step_id": "step_1", "message": "OK"}]
    assert route_after_verify(state, has_rollback=True) == "evaluate"


def test_route_after_evaluation_guardrails() -> None:
    """Valida los guardarraíles deterministas de route_after_evaluation."""
    # 1. Ciclo a reason ante NEEDS_MORE_INFO si iteration < max_iterations
    state_loop: AgentState = {
        "iteration": 1,
        "max_iterations": 3,
        "evaluation_records": [
            EvaluationRecord(
                goal_status=GoalStatus.NEEDS_MORE_INFO,
                explanation="Falta verificar el puerto 80.",
                suggested_next_action="Ejecutar curl",
                iteration=1,
                timestamp=datetime.now(UTC),
            )
        ],
    }
    assert route_after_evaluation(state_loop) == "reason"

    # 2. Guardarraíl de presupuesto: forzar conclude si iteration >= max_iterations
    state_max_iter: AgentState = {
        "iteration": 3,
        "max_iterations": 3,
        "evaluation_records": [
            EvaluationRecord(
                goal_status=GoalStatus.NEEDS_MORE_INFO,
                explanation="Sigue faltando información pero se alcanzó el límite.",
                iteration=3,
                timestamp=datetime.now(UTC),
            )
        ],
    }
    assert route_after_evaluation(state_max_iter) == "conclude"

    # 3. Guardarraíl por capacidades ausentes (BLOCKED_MISSING_CAPABILITY -> conclude)
    state_missing: AgentState = {
        "iteration": 1,
        "max_iterations": 3,
        "evaluation_records": [
            EvaluationRecord(
                goal_status=GoalStatus.BLOCKED_MISSING_CAPABILITY,
                explanation="Se requiere 'docker:logs' que no está registrada.",
                missing_capabilities=["docker:logs"],
                iteration=1,
                timestamp=datetime.now(UTC),
            )
        ],
    }
    assert route_after_evaluation(state_missing) == "conclude"

    # 4. Objetivo satisfecho (SATISFIED -> conclude)
    state_satisfied: AgentState = {
        "iteration": 1,
        "max_iterations": 3,
        "evaluation_records": [
            EvaluationRecord(
                goal_status=GoalStatus.SATISFIED,
                explanation="Todos los servicios están levantados.",
                iteration=1,
                timestamp=datetime.now(UTC),
            )
        ],
    }
    assert route_after_evaluation(state_satisfied) == "conclude"

    # 5. Compensación (requires_rollback -> rollback)
    state_rollback: AgentState = {
        "requires_rollback": True,
        "iteration": 1,
        "max_iterations": 3,
        "evaluation_records": [],
    }
    assert route_after_evaluation(state_rollback, has_rollback=True) == "rollback"


@pytest.mark.asyncio
async def test_reason_node_handles_iteration_and_injects_guidance() -> None:
    """Verifica que reason_node incremente la iteración e inyecte la retroalimentación de la evaluación previa."""
    registry = CapabilityRegistry()
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content="Respuesta en segunda iteración tras evaluar.")
    )
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec_test_1",
            thread_id="thread_test_1",
            prompt="Diagnosticar el contenedor",
        ),
        "messages": [HumanMessage(content="Diagnosticar el contenedor")],
        "iteration": 1,
        "max_iterations": 3,
        "evaluation_records": [
            EvaluationRecord(
                goal_status=GoalStatus.NEEDS_MORE_INFO,
                explanation="El contenedor web está reiniciando.",
                suggested_next_action="Revisar logs o puertos",
                iteration=1,
                timestamp=datetime.now(UTC),
            )
        ],
    }

    result = await reason_node(state, registry, llm=mock_llm)

    assert result["iteration"] == 2
    assert "Iteración 2" in result["cognitive_steps"][0].title

    # Comprobar que ainvoke recibió la guía semántica previa
    call_args = mock_llm.ainvoke.call_args[0][0]
    guidance_msgs = [
        m for m in call_args if "[Evaluación Semántica Previa (Iteración 1)]" in str(m.content)
    ]
    assert len(guidance_msgs) == 1
    assert "El contenedor web está reiniciando." in str(guidance_msgs[0].content)


@pytest.mark.asyncio
async def test_conclude_node_prioritizes_evaluation_explanation() -> None:
    """Verifica que conclude_node use EvaluationRecord.explanation y evite volcar JSON crudo."""
    registry = CapabilityRegistry()

    # Caso 1: Hay EvaluationRecord con explicación elaborada
    state_with_eval: AgentState = {
        "request": AgentInput(
            execution_id="exec_test_2",
            thread_id="thread_test_2",
            prompt="¿Cómo están los contenedores?",
        ),
        "messages": [AIMessage(content="{'raw': 'json'}")],  # Contenido JSON simulado
        "execution_records": [
            StepExecutionRecord(
                step_id="step_1",
                tool_name="docker:list",
                status=StepStatus.COMPLETED,
                output="['container-1 (restarting)']",
                duration_ms=50.0,
            )
        ],
        "evaluation_records": [
            EvaluationRecord(
                goal_status=GoalStatus.BLOCKED_MISSING_CAPABILITY,
                explanation="Se observó que el contenedor 'web' está en bucle de reinicio. Se requiere la herramienta de inspección de logs para diagnosticar la causa raíz.",
                missing_capabilities=["docker:logs"],
                iteration=1,
                timestamp=datetime.now(UTC),
            )
        ],
    }

    res = await conclude_node(state_with_eval, registry)
    output = res["output"]

    assert "Se observó que el contenedor 'web' está en bucle de reinicio" in output.response
    assert "Resultado: ['container-1" not in output.response

    # Caso 2: Sin EvaluationRecord pero con herramientas ejecutadas, no emite 'Resultado: {output}'
    state_tools_only: AgentState = {
        "request": AgentInput(
            execution_id="exec_test_3",
            thread_id="thread_test_3",
            prompt="Listar servicios",
        ),
        "messages": [],
        "execution_records": [
            StepExecutionRecord(
                step_id="step_1",
                tool_name="docker:list",
                status=StepStatus.COMPLETED,
                output={"status": "ok", "items": ["srv1", "srv2"]},
                duration_ms=45.0,
            )
        ],
        "evaluation_records": [],
    }

    res2 = await conclude_node(state_tools_only, registry)
    output2 = res2["output"]

    assert (
        "Se completaron satisfactoriamente las operaciones solicitadas mediante: docker:list"
        in output2.response
    )
    assert "Resultado: {'status': 'ok'" not in output2.response
