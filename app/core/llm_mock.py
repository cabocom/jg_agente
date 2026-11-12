# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Modelo de lenguaje simulado (MockChatModel) determinista para testing y desarrollo."""

import logging
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger("jg_agente.core.llm.mock")

GREETING_WORDS = {
    "hola",
    "saludos",
    "buenos días",
    "buenas tardes",
    "buenas noches",
    "hey",
    "hi",
    "hello",
    "adiós",
    "chao",
    "gracias",
    "cómo estás",
    "como estas",
    "qué tal",
    "que tal",
    "capacidades",
    "quién eres",
    "quien eres",
    "qué puedes hacer",
    "que puedes hacer",
}

OPERATIONAL_MARKERS = {
    "estado",
    "contenedor",
    "docker",
    "pod",
    "servicio",
    "reinicia",
    "ejecuta",
    "detén",
    "para",
    "mata",
    "log",
    "logs",
    "metric",
    "cpu",
    "memoria",
    "disco",
    "red",
    "despliega",
}


def _classify_intent_prompt(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Clasifica intenciones como saludo o acción según marcadores operativos."""
    has_op = any(m in text for m in OPERATIONAL_MARKERS)
    is_greeting = any(g in text for g in GREETING_WORDS)
    is_simple = is_greeting and not has_op
    return ("GREETING", []) if is_simple else ("ACTION", [])


def _detect_auto_tool_call(
    text: str,
    bound_tools: list[Any],
) -> list[dict[str, Any]] | None:
    """Detecta coincidencia léxica entre el prompt y las herramientas vinculadas."""
    for tool in bound_tools:
        tool_name = ""
        if isinstance(tool, BaseTool):
            tool_name = tool.name
        elif isinstance(tool, dict) and "name" in tool:
            tool_name = tool["name"]
        elif hasattr(tool, "__name__"):
            tool_name = tool.__name__

        clean_name = tool_name.lower().replace("_", " ")
        if tool_name.lower() in text or any(
            word in text for word in clean_name.split() if len(word) > 3
        ):
            call_id = f"call_{uuid.uuid4().hex[:8]}"
            logger.debug("MockChatModel auto-generando tool_call para '%s'", tool_name)
            return [
                {
                    "id": call_id,
                    "name": tool_name,
                    "args": {"query": text},
                    "type": "tool_call",
                }
            ]
    return None


class MockChatModel(BaseChatModel):
    """Modelo de chat simulado y determinista para testing y desarrollo local."""

    response_content: str = Field(
        default="Esta es una respuesta simulada del agente.",
        description="Contenido del mensaje de respuesta si no hay tool_calls",
    )
    tool_calls_to_return: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Lista explícita de tool_calls a retornar por el modelo",
    )
    bound_tools: list[Any] = Field(
        default_factory=list,
        description="Herramientas vinculadas mediante bind_tools()",
    )
    auto_tool_calls: bool = Field(
        default=True,
        description="Infiere automáticamente tool calls si el prompt coincide con herramientas vinculadas",
    )

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        """Vincula herramientas al modelo retornando una instancia clonada."""
        clone = self.model_copy()
        clone.bound_tools = list(tools)
        return clone.bind(**kwargs)

    def _determine_output(self, messages: list[BaseMessage]) -> tuple[str, list[dict[str, Any]]]:
        """Calcula el contenido y tool_calls a generar según los mensajes recibidos."""
        if self.tool_calls_to_return:
            return "", list(self.tool_calls_to_return)

        last_human_text = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_text = str(msg.content).lower()
                break

        first_sys = (
            messages[0].content if messages and isinstance(messages[0], SystemMessage) else ""
        )
        if "clasificador de intenciones" in str(first_sys).lower():
            return _classify_intent_prompt(last_human_text)

        if self.auto_tool_calls and self.bound_tools and last_human_text:
            matched_calls = _detect_auto_tool_call(last_human_text, self.bound_tools)
            if matched_calls:
                return "", matched_calls

        return self.response_content, []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        content, tool_calls = self._determine_output(messages)
        ai_msg = AIMessage(content=content, tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager=None, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "mock_chat_model"
