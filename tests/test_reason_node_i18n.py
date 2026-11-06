# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests de internacionalización (i18n) en el nodo reason.py."""

from typing import Any

import pytest
from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.outputs import ChatResult
from pydantic import Field

from app.core.llm import MockChatModel
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import AgentExecutionStatus, AgentState
from app.nodes.reason import reason_node


class RecordingMockChatModel(MockChatModel):
    """Mock que registra todos los mensajes pasados por cada invocación."""

    captured_messages: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.captured_messages.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.captured_messages.append(messages)
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "expected_phrase", "expected_title"),
    [
        (
            "es",
            "Eres un agente inteligente autónomo de ejecución",
            "Razonamiento y Respuesta Directa",
        ),
        (
            "en",
            "You are an intelligent, autonomous, goal-oriented execution agent",
            "Reasoning & Direct Response",
        ),
        (
            "fr",
            "Vous êtes un agent d'exécution autonome et intelligent",
            "Raisonnement et Réponse Directe",
        ),
        (
            "de",
            "Sie sind ein intelligenter, autonomer, zielorientierter Ausführungsagent",
            "Kognitive Analyse & Direkte Antwort",
        ),
        (
            "it",
            "Sei un agente intelligente autonomo di esecuzione",
            "Ragionamento e Risposta Diretta",
        ),
    ],
)
async def test_reason_node_i18n_system_prompt_and_steps(
    locale: str,
    expected_phrase: str,
    expected_title: str,
) -> None:
    """Verifica que reason_node inyecta el SystemMessage y CognitiveStep en el idioma solicitado."""
    registry = CapabilityRegistry()
    mock_llm = RecordingMockChatModel(
        response_content="Respuesta de prueba",
        auto_tool_calls=False,
    )

    initial_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-i18n-01",
            thread_id="th-i18n-01",
            prompt="Hello agent",
            locale=locale,
        ),
        "messages": [],
        "status": AgentExecutionStatus.IDLE,
    }

    output = await reason_node(
        state=initial_state,
        registry=registry,
        llm=mock_llm,
    )

    # 1. Comprobar que el SystemMessage contiene la frase correspondiente al idioma
    assert len(mock_llm.captured_messages) > 0
    invoked_msgs = mock_llm.captured_messages[0]
    system_msgs = [m for m in invoked_msgs if isinstance(m, SystemMessage)]
    assert len(system_msgs) == 1
    system_content = str(system_msgs[0].content)
    assert expected_phrase in system_content

    # 2. Comprobar que el CognitiveStep emitido está localizado
    cognitive_steps = output.get("cognitive_steps", [])
    assert len(cognitive_steps) >= 1
    step = cognitive_steps[0]
    assert step.title == expected_title
    assert step.details.get("locale") == locale


@pytest.mark.asyncio
async def test_reason_node_i18n_fallback_to_default_on_unknown_locale() -> None:
    """Verifica que ante un locale desconocido, se recurre a la plantilla por defecto (es)."""
    registry = CapabilityRegistry()
    mock_llm = RecordingMockChatModel(
        response_content="Respuesta de fallback",
        auto_tool_calls=False,
    )

    initial_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-fallback-01",
            thread_id="th-fallback-01",
            prompt="Olá mundo",
            locale="pt_BR",  # No soportado directamente
        ),
        "messages": [],
        "status": AgentExecutionStatus.IDLE,
    }

    output = await reason_node(
        state=initial_state,
        registry=registry,
        llm=mock_llm,
    )

    invoked_msgs = mock_llm.captured_messages[0]
    system_msgs = [m for m in invoked_msgs if isinstance(m, SystemMessage)]
    system_content = str(system_msgs[0].content)
    # Debe haber usado 'es' por defecto
    assert "Eres un agente inteligente autónomo" in system_content

    cognitive_steps = output.get("cognitive_steps", [])
    assert len(cognitive_steps) >= 1
    step = cognitive_steps[0]
    assert step.title == "Razonamiento y Respuesta Directa"
    assert step.details.get("locale") == "es"


@pytest.mark.asyncio
async def test_reason_node_i18n_tool_call_localized_step() -> None:
    """Verifica que reason_node emite cognitive_step localizado cuando hay tool_calls."""
    registry = CapabilityRegistry()
    mock_llm = RecordingMockChatModel(
        tool_calls_to_return=[
            {
                "id": "call_1",
                "name": "test_tool",
                "args": {},
                "type": "tool_call",
            }
        ]
    )

    initial_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-i18n-tool-01",
            thread_id="th-i18n-tool-01",
            prompt="Run test tool",
            locale="fr",
        ),
        "messages": [],
        "status": AgentExecutionStatus.IDLE,
    }

    output = await reason_node(
        state=initial_state,
        registry=registry,
        llm=mock_llm,
    )

    cognitive_steps = output.get("cognitive_steps", [])
    assert len(cognitive_steps) >= 1
    step = cognitive_steps[0]
    assert step.title == "Raisonnement et Interprétation Cognitive"
    assert step.details.get("locale") == "fr"
