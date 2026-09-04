"""Nodo cognitivo troncal de razonamiento (reason) para jg_agente.

Procesa el estímulo normalizado (AgentInput) junto con la memoria conversacional acumulada
en StateGraph mediante un LLM configurable. Si el modelo decide que se requiere invocar
capacidades externas, genera tool_calls estructurados; en caso contrario, formula una
respuesta directa para resolver la solicitud.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.runnables import Runnable

from app.core.config import settings
from app.core.llm import get_chat_model
from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
    IntentModel,
)

logger = logging.getLogger("jg_agente.nodes.reason")


def _is_simple_greeting_or_chat(prompt: str) -> bool:
    """Determina si un estímulo es un saludo o interacción conversacional simple sin tarea operativa."""
    if not prompt:
        return True
    p = prompt.strip().lower()
    greetings = {
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
    }
    words = set(p.replace("¿", "").replace("?", "").replace("!", "").replace("¡", "").split())
    if words and words.issubset(greetings):
        return True
    return len(words) <= 3 and any(g in words for g in ("hola", "saludos", "hey", "hello", "hi"))


async def reason_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Ejecuta el ciclo de razonamiento del LLM sobre el estado actual del agente.

    Args:
        state: Estado global actual del grafo (AgentState).
        registry: Catálogo de capacidades para enlazar herramientas disponibles.
        llm: Instancia opcional de BaseChatModel (si es None, se resuelve vía get_chat_model()).
        system_prompt: Directriz opcional del sistema (si es None, se utiliza la de configuración).

    Returns:
        Diccionario con las mutaciones parciales de estado para LangGraph (messages, intent, status, audit_trail).
    """
    model = llm or get_chat_model()
    existing_messages = list(state.get("messages") or [])

    # 1. Recuperar el estímulo textual principal
    prompt = ""
    req = state.get("request")
    if req and req.prompt:
        prompt = req.prompt.strip()

    # 2. Reconstrucción y enriquecimiento de la memoria conversacional
    messages_to_send: list[BaseMessage] = []
    has_system = any(isinstance(m, SystemMessage) for m in existing_messages)

    if not has_system:
        sys_content = system_prompt or settings.DEFAULT_SYSTEM_PROMPT
        messages_to_send.append(SystemMessage(content=sys_content))

    messages_to_send.extend(existing_messages)

    # Si hay un nuevo prompt en request que no está en el historial, añadirlo
    if prompt:
        has_current_human = (
            len(existing_messages) > 0
            and isinstance(existing_messages[-1], HumanMessage)
            and existing_messages[-1].content == prompt
        )
        if not has_current_human:
            messages_to_send.append(HumanMessage(content=prompt))

    # 3. Enlace dinámico de herramientas (Tool Binding)
    tools = registry.get_langchain_tools()
    model_to_invoke: Runnable[Any, Any] = model
    if tools and hasattr(model, "bind_tools"):
        try:
            model_to_invoke = model.bind_tools(tools)
        except Exception as exc:
            logger.warning("No se pudieron vincular las herramientas al LLM: %s", exc)

    # 4. Invocación asíncrona del LLM
    try:
        raw_response = await model_to_invoke.ainvoke(messages_to_send)
    except NotImplementedError:
        # Fallback para modelos que solo implementan invoke síncrono
        raw_response = model_to_invoke.invoke(messages_to_send)

    ai_message: AIMessage
    if isinstance(raw_response, AIMessage):
        ai_message = raw_response
    else:
        ai_message = AIMessage(content=str(getattr(raw_response, "content", raw_response)))
    # 5. Análisis del resultado: ¿tool_calls, plan o respuesta directa?
    has_tool_calls = bool(ai_message.tool_calls)
    planner_engine = registry.get_planner()

    if has_tool_calls:
        logger.info(
            "[reason_node] El modelo generó %d tool call(s)",
            len(ai_message.tool_calls),
        )
        intent = IntentModel(
            goal=prompt or "Ejecución de herramientas operativas",
            action_type="act",
            parameters={"tool_calls": ai_message.tool_calls},
            confidence=1.0,
            reasoning=str(ai_message.content)
            if ai_message.content
            else "Invocación de herramientas requerida.",
        )
        audit_details = {
            "action_type": "act",
            "tool_calls_count": len(ai_message.tool_calls),
            "tools": [tc.get("name") for tc in ai_message.tool_calls],
        }
    elif planner_engine is not None and not _is_simple_greeting_or_chat(prompt):
        logger.info(
            "[reason_node] Solicitud operativa detectada con planificador disponible ('%s')",
            planner_engine.name,
        )
        intent = IntentModel(
            goal=prompt or "Elaboración de plan de ejecución",
            action_type="plan",
            parameters={"planner": planner_engine.name},
            confidence=1.0,
            reasoning=f"Se requiere planificar la ejecución mediante el motor '{planner_engine.name}'.",
        )
        audit_details = {
            "action_type": "plan",
            "planner": planner_engine.name,
        }
    else:
        logger.info(
            "[reason_node] El modelo generó respuesta directa sin herramientas ni planificación"
        )
        intent = IntentModel(
            goal=prompt or "Resolución directa",
            action_type="conclude",
            parameters={"response": ai_message.content},
            confidence=1.0,
            reasoning="Respuesta directa generada por el LLM.",
        )
        audit_details = {
            "action_type": "conclude",
            "response_length": len(str(ai_message.content)),
        }

    return {
        "status": AgentExecutionStatus.REASONING,
        "intent": intent,
        "messages": [ai_message],
        "audit_trail": [
            AuditRecord(
                event_type="reasoning_completed",
                actor="llm_reason_node",
                details=audit_details,
                timestamp=datetime.now(UTC),
            )
        ],
    }
