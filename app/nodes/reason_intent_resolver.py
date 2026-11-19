# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Resolución de intención, deduplicación y formulación de acciones para el nodo reason."""

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolCall

from app.core.config import settings
from app.core.llm import MockChatModel
from app.core.registry import CapabilityRegistry
from app.models.state import AgentState, IntentModel
from app.nodes.reason_classifier import is_simple_greeting_or_chat_llm
from app.nodes.reason_plan_expander import expand_full_action_plan_with_llm
from app.prompts import get_prompt_manager

logger = logging.getLogger("jg_agente.nodes.reason_intent_resolver")


def _normalize_args(d: dict[str, Any]) -> dict[str, Any]:
    """Normaliza argumentos eliminando request_id efímero."""
    return {k: v for k, v in d.items() if k != "request_id"}


def _filter_duplicate_tool_calls(
    tool_calls: list[ToolCall],
    past_executions: list[tuple[Any, dict[str, Any]]],
) -> list[ToolCall]:
    """Filtra llamadas a herramientas con argumentos idénticos a los ya ejecutados."""

    def _is_duplicate(tc: ToolCall) -> bool:
        tc_name = tc.get("name")
        tc_args = _normalize_args(tc.get("args") or {})
        for p_name, p_args in past_executions:
            if p_name == tc_name and _normalize_args(p_args) == tc_args:
                return True
        return False

    return [tc for tc in tool_calls if not _is_duplicate(tc)]


def _format_tc_summary(tc: Any) -> str:
    """Genera un resumen legible de una llamada a herramienta."""
    name = str(tc.get("name") or "tool")
    args = tc.get("args") or {}
    if isinstance(args, dict):
        cmd = (
            args.get("command")
            or args.get("target_url")
            or args.get("url")
            or args.get("target")
            or args.get("query")
        )
        if cmd:
            return f"{name} → '{cmd}'"
    return name


async def _handle_tool_calls_decision(
    ai_message: AIMessage,
    state: AgentState,
    model: BaseChatModel,
    registry: CapabilityRegistry,
    prompt: str,
    locale: str,
    past_executions: list[tuple[Any, dict[str, Any]]],
) -> tuple[IntentModel, dict[str, Any], str, str, str]:
    """Procesa llamadas a herramientas, deduplica y expande planes si aplica."""
    prompt_mgr = get_prompt_manager()
    active_tool_calls = _filter_duplicate_tool_calls(ai_message.tool_calls, past_executions)

    if not active_tool_calls and ai_message.tool_calls:
        logger.info(
            "[reason_node] Todas las herramientas invocadas ya fueron ejecutadas con argumentos idénticos."
        )
        intent = IntentModel(
            goal=prompt or "Resolución con evidencia existente",
            action_type="conclude",
            parameters={
                "response": ai_message.content
                or "Operaciones completadas con la evidencia recopilada."
            },
            confidence=1.0,
            reasoning="Las herramientas invocadas ya fueron ejecutadas previamente con idénticos parámetros.",
        )
        audit_details = {
            "action_type": "conclude",
            "deduplicated_calls": len(ai_message.tool_calls),
        }
        title, action, desc = prompt_mgr.get_cognitive_meta("conclude_dedup", locale=locale)
        return intent, audit_details, title, action, desc

    plan_steps_meta: list[dict[str, Any]] = []
    is_real_llm = not isinstance(model, MockChatModel) and settings.LLM_PROVIDER not in (
        "mock",
        "fake",
        "test",
    )

    if is_real_llm and state.get("approval") is None and len(active_tool_calls) == 1:
        expanded_calls, expanded_meta = await expand_full_action_plan_with_llm(
            model=model,
            prompt=prompt,
            initial_tool_calls=active_tool_calls,
            registry=registry,
            past_executions=past_executions,
            locale=locale,
        )
        if len(expanded_calls) >= 1 and expanded_meta:
            active_tool_calls = expanded_calls
            plan_steps_meta = expanded_meta
            ai_message.tool_calls = active_tool_calls

    tool_names = [tc.get("name") for tc in active_tool_calls]
    calls_summary = ", ".join(_format_tc_summary(tc) for tc in active_tool_calls)
    logger.info(
        "[reason_node] El modelo generó %d tool call(s) activas: %s",
        len(active_tool_calls),
        calls_summary,
    )

    intent_params: dict[str, Any] = {"tool_calls": active_tool_calls}
    if plan_steps_meta:
        intent_params["plan_steps_metadata"] = plan_steps_meta

    intent = IntentModel(
        goal=prompt or "Ejecución de herramientas operativas",
        action_type="act",
        parameters=intent_params,
        confidence=1.0,
        reasoning=str(ai_message.content)
        if ai_message.content
        else f"Invocación requerida para: {calls_summary}",
    )
    audit_details = {
        "action_type": "act",
        "tool_calls_count": len(active_tool_calls),
        "tools": tool_names,
    }
    title, action, desc = prompt_mgr.get_cognitive_meta(
        "act", locale=locale, count=len(active_tool_calls), summary=calls_summary
    )
    return intent, audit_details, title, action, desc


async def resolve_reason_intent_and_steps(
    ai_message: AIMessage,
    state: AgentState,
    model: BaseChatModel,
    registry: CapabilityRegistry,
    prompt: str,
    locale: str,
) -> tuple[IntentModel, dict[str, Any], str, str, str]:
    """Determina la intención final (act, plan o conclude) y sus metadatos cognitivos."""
    prompt_mgr = get_prompt_manager()

    if ai_message.tool_calls:
        past_executions = [
            (getattr(r, "tool_name", None), getattr(r, "tool_args", {}) or {})
            for r in (state.get("execution_records") or [])
            if str(getattr(r, "status", "")).lower() in ("completed", "stepstatus.completed")
        ]
        return await _handle_tool_calls_decision(
            ai_message, state, model, registry, prompt, locale, past_executions
        )

    planner_engine = registry.get_planner()
    if planner_engine is not None and not await is_simple_greeting_or_chat_llm(
        model, prompt, locale=locale
    ):
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
        audit_details: dict[str, Any] = {"action_type": "plan", "planner": planner_engine.name}
        title, action, desc = prompt_mgr.get_cognitive_meta(
            "plan", locale=locale, planner=planner_engine.name
        )
        return intent, audit_details, title, action, desc

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
    title, action, desc = prompt_mgr.get_cognitive_meta("conclude_direct", locale=locale)
    return intent, audit_details, title, action, desc
