# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo cognitivo troncal de razonamiento (reason) para jg_agente.

Procesa el estímulo normalizado (AgentInput) junto con la memoria conversacional acumulada
en StateGraph mediante un LLM configurable. Si el modelo decide que se requiere invocar
capacidades externas, genera tool_calls estructurados; en caso contrario, formula una
respuesta directa para resolver la solicitud.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from app.core.llm import get_chat_model
from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
)
from app.nodes.reason_classifier import (
    is_simple_greeting_or_chat_llm as _is_simple_greeting_or_chat_llm,
)
from app.nodes.reason_context import build_reason_messages, resolve_reason_locale
from app.nodes.reason_intent_resolver import resolve_reason_intent_and_steps
from app.nodes.reason_plan_expander import (
    expand_full_action_plan_with_llm as _expand_full_action_plan_with_llm,
)

logger = logging.getLogger("jg_agente.nodes.reason")

__all__ = [
    "reason_node",
    "_expand_full_action_plan_with_llm",
    "_is_simple_greeting_or_chat_llm",
]


async def _invoke_llm(
    model: BaseChatModel, messages: list[Any], registry: CapabilityRegistry
) -> tuple[AIMessage, float]:
    """Invoca al LLM vinculando herramientas si procede y computa duración."""
    tools = registry.get_langchain_tools()
    model_to_invoke: Runnable[Any, Any] = model
    if tools and hasattr(model, "bind_tools"):
        model_to_invoke = model.bind_tools(tools)

    start_llm = time.perf_counter()
    try:
        raw_response = await model_to_invoke.ainvoke(messages)
    except NotImplementedError:
        raw_response = model_to_invoke.invoke(messages)
    duration_ms = max(0.0, round((time.perf_counter() - start_llm) * 1000.0, 2))

    if isinstance(raw_response, AIMessage):
        ai_message = raw_response
    else:
        ai_message = AIMessage(content=str(getattr(raw_response, "content", raw_response)))

    return ai_message, duration_ms


async def reason_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Ejecuta el ciclo de razonamiento del LLM sobre el estado actual del agente."""
    model = llm or get_chat_model()
    locale, prompt = resolve_reason_locale(state, registry)
    messages_to_send, current_iteration = build_reason_messages(
        state, prompt, locale, system_prompt
    )

    ai_message, duration_llm_ms = await _invoke_llm(model, messages_to_send, registry)

    (
        intent,
        audit_details,
        step_title,
        step_action,
        step_description,
    ) = await resolve_reason_intent_and_steps(
        ai_message=ai_message,
        state=state,
        model=model,
        registry=registry,
        prompt=prompt,
        locale=locale,
    )

    if current_iteration > 1:
        step_title = f"{step_title} (Iteración {current_iteration})"

    cognitive_step = CognitiveStepRecord(
        step_id=f"cog_reason_{int(time.time() * 1000)}",
        node="reason",
        title=step_title,
        action=step_action,
        description=step_description,
        status="completed",
        details={
            "goal": intent.goal,
            "action_type": intent.action_type,
            "reasoning": intent.reasoning,
            "tool_calls": ai_message.tool_calls if ai_message.tool_calls else [],
            "response_preview": str(ai_message.content)[:300] if ai_message.content else None,
            "iteration": current_iteration,
            "locale": locale,
        },
        duration_ms=duration_llm_ms,
        timestamp=datetime.now(UTC),
    )

    return {
        "status": AgentExecutionStatus.REASONING,
        "intent": intent,
        "iteration": current_iteration,
        "messages": [ai_message],
        "cognitive_steps": [cognitive_step],
        "audit_trail": [
            AuditRecord(
                event_type="reasoning_completed",
                actor="llm_reason_node",
                details=audit_details,
                timestamp=datetime.now(UTC),
            )
        ],
    }
