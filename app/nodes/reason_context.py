# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Construcción de contexto conversacional y resolución de locale para el nodo reason."""

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.core.config import settings
from app.core.registry import CapabilityRegistry
from app.models.state import AgentState
from app.prompts import get_prompt_manager


def resolve_reason_locale(state: AgentState, registry: CapabilityRegistry) -> tuple[str, str]:
    """Recupera el estímulo principal y resuelve el locale correspondiente."""
    prompt = ""
    req = state.get("request")
    if req and req.prompt:
        prompt = req.prompt.strip()

    req_locale = getattr(req, "locale", None) if req else None

    plugin_default_locale: str | None = None
    try:
        loaded_plugins = registry.list_plugins()
        if len(loaded_plugins) == 1:
            plugin_default_locale = getattr(loaded_plugins[0], "default_locale", None)
    except Exception:
        pass

    prompt_mgr = get_prompt_manager()
    locale = prompt_mgr.resolve_locale(
        requested_locale=req_locale,
        plugin_default=plugin_default_locale,
        system_default=getattr(settings, "DEFAULT_LOCALE", "es"),
    )
    return locale, prompt


def _build_evaluation_guidance(
    state: AgentState,
    current_iteration: int,
    locale: str,
) -> HumanMessage | None:
    """Genera mensaje guía con el feedback del evaluador si venimos de un ciclo iterativo."""
    eval_records = list(state.get("evaluation_records") or [])
    if not eval_records:
        return None

    prompt_mgr = get_prompt_manager()
    last_eval = eval_records[-1]
    executed_summary = [
        f"{getattr(r, 'tool_name', '')}({(getattr(r, 'tool_args', {}) or {}).get('command') or getattr(r, 'tool_args', {})})"
        for r in (state.get("execution_records") or [])
    ]
    already_done_prefix = {
        "es": "\nOperaciones ya ejecutadas (NO repetir): ",
        "en": "\nOperations already executed (DO NOT repeat): ",
        "fr": "\nOpérations déjà exécutées (NE PAS répéter) : ",
        "de": "\nBereits ausgeführte Operationen (NICHT wiederholen): ",
        "it": "\nOperazioni già eseguite (NON ripetere): ",
    }.get(locale, "\nOperaciones ya ejecutadas (NO repetir): ")
    already_done_note = (
        f"{already_done_prefix}{', '.join(executed_summary)}" if executed_summary else ""
    )
    default_next_action = {
        "es": "Continuar con el objetivo original utilizando las herramientas disponibles con nuevos parámetros.",
        "en": "Continue with original goal using available tools with new parameters.",
        "fr": "Poursuivre l'objectif initial à l'aide des outils disponibles avec de nouveaux paramètres.",
        "de": "Das ursprüngliche Ziel mit den verfügbaren Werkzeugen und neuen Parametern fortsetzen.",
        "it": "Continuare con l'obiettivo originale utilizzando gli strumenti disponibili con nuovi parametri.",
    }.get(
        locale,
        "Continuar con el objetivo original utilizando las herramientas disponibles con nuevos parámetros.",
    )
    guidance_text = prompt_mgr.render(
        "guidance",
        locale=locale,
        iteration=current_iteration - 1,
        explanation=last_eval.explanation,
        suggested_next_action=last_eval.suggested_next_action or default_next_action,
        already_done_note=already_done_note,
    )
    return HumanMessage(content=guidance_text)


SHORT_ANSWER_DIRECTIVE = (
    "\n\n[MODO RESPUESTA CORTA / SHORT ANSWER ACTIVADO]\n"
    "- Responde de forma MUY CORTA, CONCISA Y DIRECTA (máximo 1 o 2 oraciones breves).\n"
    "- NUNCA cites fuentes, ni enlaces web, ni URLs (nada de 'https://...', 'AS.com', 'Marca.com', 'fuente:').\n"
    "- Formato limpio y fluido, sin sintaxis markdown (sin asteriscos, sin viñetas, sin negritas)."
)


def is_short_answer_request(state: AgentState | dict[str, Any]) -> bool:
    """Determina si la solicitud requiere una respuesta corta y concisa (short_answer)."""
    req = state.get("request")
    if not req:
        return False

    params = getattr(req, "parameters", None) or {}
    meta = getattr(req, "metadata", None) or {}

    if isinstance(params, dict):
        if params.get("short_answer") or params.get("verbosity") == "short":
            return True
        if params.get("is_telephony") or params.get("simulation_type") in (
            "asterisk_voice",
            "telephony_voice",
        ):
            return True
        ch = str(params.get("channel", "")).lower()
        if ch.startswith("sip/") or "asterisk" in ch or "voice" in ch:
            return True

    if isinstance(meta, dict):
        if meta.get("short_answer") or meta.get("verbosity") == "short":
            return True
        if meta.get("simulation_type") in ("asterisk_voice", "telephony_voice") or meta.get(
            "is_telephony"
        ):
            return True
        ch = str(meta.get("channel", "")).lower()
        if ch.startswith("sip/") or "asterisk" in ch or "voice" in ch:
            return True

    return False


def is_voice_telephony_request(state: AgentState | dict[str, Any]) -> bool:
    """Alias retrocompatible para is_short_answer_request."""
    return is_short_answer_request(state)


def build_reason_messages(
    state: AgentState,
    prompt: str,
    locale: str,
    system_prompt: str | None = None,
) -> tuple[list[BaseMessage], int]:
    """Construye y enriquece la lista de mensajes conversacionales para invocar al LLM."""
    existing_messages = list(state.get("messages") or [])
    prompt_mgr = get_prompt_manager()
    messages_to_send: list[BaseMessage] = []
    is_short = is_short_answer_request(state)

    has_system = any(isinstance(m, SystemMessage) for m in existing_messages)
    if not has_system:
        sys_content = prompt_mgr.get_system_prompt(
            locale=locale,
            verbosity=getattr(settings, "AGENT_VERBOSITY", "concise"),
            base_prompt=system_prompt or getattr(settings, "AGENT_SYSTEM_PROMPT", None),
        )
        if is_short:
            sys_content += SHORT_ANSWER_DIRECTIVE
        messages_to_send.append(SystemMessage(content=sys_content))
    elif is_short:
        messages_to_send.append(SystemMessage(content=SHORT_ANSWER_DIRECTIVE))

    messages_to_send.extend(existing_messages)

    eval_records = list(state.get("evaluation_records") or [])
    current_iteration = int(state.get("iteration", 1))
    if eval_records:
        current_iteration += 1

    if prompt:
        has_current_human = (
            len(existing_messages) > 0
            and isinstance(existing_messages[-1], HumanMessage)
            and existing_messages[-1].content == prompt
        )
        if not has_current_human:
            messages_to_send.append(HumanMessage(content=prompt))

    guidance_msg = _build_evaluation_guidance(state, current_iteration, locale)
    if guidance_msg is not None:
        messages_to_send.append(guidance_msg)

    return messages_to_send, current_iteration
