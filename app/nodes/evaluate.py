# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo cognitivo de evaluación semántica y Capability-Awareness (evaluate) para jg_agente.

Evalúa si la evidencia recopilada tras la ejecución de herramientas responde de forma
completa al objetivo del usuario o si se requieren acciones adicionales.
Incorpora capability-awareness: si detecta una anomalía o necesidad técnica ausente
en el catálogo de herramientas disponibles (ej. requerir docker:logs cuando no existe),
emite GoalStatus.BLOCKED_MISSING_CAPABILITY y formula una explicación proactiva.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.config import settings
from app.core.llm import get_chat_model
from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
    EvaluationRecord,
    GoalStatus,
)
from app.nodes.evaluate_parser import extract_json as _extract_json
from app.nodes.evaluate_parser import parse_evaluation_response
from app.nodes.evaluate_prompt import (
    build_evaluate_system_prompt,
    build_evaluate_user_payload,
)

logger = logging.getLogger("jg_agente.nodes.evaluate")

__all__ = ["evaluate_node", "_extract_json"]


def _collect_tool_messages(messages: list[Any], max_obs_chars: int = 2500) -> list[str]:
    """Extrae y formatea mensajes de herramientas recibidos en el estado."""
    tool_messages: list[str] = []
    half_obs = max_obs_chars // 2
    for msg in messages:
        if isinstance(msg, ToolMessage):
            raw_c = str(msg.content or "")
            capped_c = (
                raw_c[:half_obs]
                + f"\n... [observación central omitida ({len(raw_c)} chars totales)] ...\n"
                + raw_c[-half_obs:]
                if len(raw_c) > max_obs_chars
                else raw_c
            )
            tool_messages.append(f"[{msg.name or 'Tool'}]: {capped_c}")
    return tool_messages


async def evaluate_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Evalúa semánticamente el estado del objetivo y la suficiencia de la evidencia técnica."""
    start_time = time.perf_counter()
    iteration = int(state.get("iteration", 1))

    prompt = ""
    req = state.get("request")
    if req and req.prompt:
        prompt = req.prompt.strip()

    available_tools = [
        {"name": t.name, "description": t.description, "category": t.category}
        for t in registry.list_tools()
    ]
    tool_names_available = {t["name"] for t in available_tools}

    exec_records = state.get("execution_records") or []
    tool_messages = _collect_tool_messages(state.get("messages") or [])
    errors = state.get("errors") or []
    error_summaries = [f"[{e.code}]: {e.message}" for e in errors]

    verbosity = getattr(settings, "AGENT_VERBOSITY", "concise").lower().strip()
    system_prompt = build_evaluate_system_prompt(verbosity)
    user_message_content = build_evaluate_user_payload(
        prompt=prompt,
        iteration=iteration,
        available_tools=available_tools,
        exec_records=exec_records,
        tool_messages=tool_messages,
        error_summaries=error_summaries,
    )

    model = llm or get_chat_model()
    messages_to_send = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message_content),
    ]

    try:
        try:
            raw_res = await model.ainvoke(messages_to_send)
        except NotImplementedError:
            raw_res = model.invoke(messages_to_send)

        content = (
            str(raw_res.content)
            if isinstance(raw_res, AIMessage)
            else str(getattr(raw_res, "content", raw_res))
        )
        goal_status, explanation, missing_capabilities, suggested_next_action = (
            parse_evaluation_response(
                content=content, errors=errors, tool_names_available=tool_names_available
            )
        )
    except Exception as exc:
        logger.error("[evaluate_node] Fallo invocando al evaluador LLM: %s", exc)
        explanation = f"Evaluación defensiva ante indisponibilidad del modelo evaluador: {exc}"
        goal_status = GoalStatus.FAILED if errors else GoalStatus.SATISFIED
        missing_capabilities = []
        suggested_next_action = None

    duration_ms = max(0.0, round((time.perf_counter() - start_time) * 1000.0, 2))

    eval_record = EvaluationRecord(
        iteration=iteration,
        goal_status=goal_status,
        explanation=explanation,
        missing_capabilities=missing_capabilities,
        suggested_next_action=suggested_next_action,
        timestamp=datetime.now(UTC),
    )

    cognitive_step = CognitiveStepRecord(
        step_id=f"cog_eval_{iteration}_{int(time.time() * 1000)}",
        node="evaluate",
        title=f"Evaluación Semántica (Iteración {iteration})",
        action=f"Estado del Objetivo: {goal_status.value.upper()}",
        description=explanation,
        status="completed",
        details={
            "iteration": iteration,
            "goal_status": goal_status.value,
            "missing_capabilities": missing_capabilities,
            "suggested_next_action": suggested_next_action,
        },
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )

    logger.info(
        "[evaluate_node] Iteración %d evaluada con veredicto '%s' en %.2f ms. Faltantes: %s",
        iteration,
        goal_status.value,
        duration_ms,
        missing_capabilities,
    )

    return {
        "evaluation_records": [eval_record],
        "cognitive_steps": [cognitive_step],
        "is_resolved": (goal_status == GoalStatus.SATISFIED),
        "audit_trail": [
            AuditRecord(
                event_type="evaluation_completed",
                actor="evaluate_node",
                details={
                    "iteration": iteration,
                    "goal_status": goal_status.value,
                    "missing_capabilities": missing_capabilities,
                    "duration_ms": duration_ms,
                },
                timestamp=datetime.now(UTC),
            )
        ],
    }
