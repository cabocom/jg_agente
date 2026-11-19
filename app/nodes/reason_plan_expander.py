# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Expansión de planes de acción completos mediante LLM antes de HITL."""

import json
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
)

from app.core.registry import CapabilityRegistry
from app.models.tools import RiskLevel
from app.prompts import get_prompt_manager

logger = logging.getLogger("jg_agente.nodes.reason_plan_expander")


def _has_mutative_actions(
    prompt: str,
    initial_tool_calls: list[ToolCall],
    registered_tools: dict[str, Any],
    locale: str,
) -> bool:
    """Verifica si la solicitud o las herramientas invocadas implican mutaciones."""
    prompt_mgr = get_prompt_manager()
    for tc in initial_tool_calls:
        t_def = registered_tools.get(str(tc.get("name") or ""))
        if t_def and (
            not getattr(t_def, "read_only", True)
            or t_def.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        ):
            return True

    p_low = prompt.lower()
    mutative_keywords = prompt_mgr.get_mutative_keywords(locale)
    return any(kw in p_low for kw in mutative_keywords)


def _build_planning_catalog(registry: CapabilityRegistry) -> str:
    """Construye la descripción textual del catálogo de herramientas para el planificador."""
    tools_spec_lines: list[str] = []
    for t in registry.list_tools():
        is_mut = not getattr(t, "read_only", True) or t.risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )
        tipo_str = (
            f"MUTATIVA (Riesgo {t.risk_level.value.upper()})"
            if is_mut
            else "SOLO LECTURA (Riesgo LOW)"
        )
        tools_spec_lines.append(f"- {t.name} [tipo={tipo_str}]: {t.description}")
    return "\n".join(tools_spec_lines)


def _parse_planning_response(
    raw_text: str,
    registered_tools: dict[str, Any],
) -> tuple[list[ToolCall], list[dict[str, Any]]]:
    """Extrae llamadas y metadatos de pasos del JSON emitido por el LLM."""
    if "```" in raw_text:
        for part in raw_text.split("```"):
            part_clean = part.strip()
            if part_clean.startswith("json"):
                part_clean = part_clean[4:].strip()
            if part_clean.startswith("{") and part_clean.endswith("}"):
                raw_text = part_clean
                break

    start_idx = raw_text.find("{")
    end_idx = raw_text.rfind("}")
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return [], []

    parsed = json.loads(raw_text[start_idx : end_idx + 1])
    raw_steps = parsed.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return [], []

    expanded_calls: list[ToolCall] = []
    steps_meta: list[dict[str, Any]] = []

    for idx, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            continue
        t_name = str(item.get("tool_name") or item.get("name") or "").strip()
        if t_name not in registered_tools:
            continue
        t_args = item.get("tool_args") or item.get("args") or {}
        if not isinstance(t_args, dict):
            continue
        if "request_id" not in t_args:
            t_args["request_id"] = f"step_{idx}"
        call_id = f"step_{idx}"
        desc = str(item.get("description") or item.get("action") or f"Ejecutar {t_name}").strip()
        t_def = registered_tools[t_name]
        is_mut = not getattr(t_def, "read_only", True) or t_def.risk_level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        )
        expanded_calls.append(ToolCall(name=t_name, args=t_args, id=call_id, type="tool_call"))
        steps_meta.append(
            {
                "index": idx,
                "step_id": call_id,
                "tool_name": t_name,
                "tool": t_name,
                "command": t_args.get("command")
                or t_args.get("target_url")
                or t_args.get("url")
                or t_args.get("target")
                or "",
                "action": desc,
                "description": desc,
                "risk_level": t_def.risk_level.value.upper(),
                "mutative": is_mut,
                "read_only": not is_mut,
                "reversible": bool(t_def.reversible),
            }
        )

    return expanded_calls, steps_meta


def _filter_past_executions(
    expanded_calls: list[ToolCall],
    steps_meta: list[dict[str, Any]],
    past_executions: list[tuple[Any, dict[str, Any]]],
) -> tuple[list[ToolCall], list[dict[str, Any]]]:
    """Elimina pasos que ya fueron ejecutados previamente."""
    filtered_calls: list[ToolCall] = []
    filtered_meta: list[dict[str, Any]] = []
    for tc_item, meta_item in zip(expanded_calls, steps_meta, strict=False):
        tc_norm = {k: v for k, v in (tc_item.get("args") or {}).items() if k != "request_id"}
        already_ran = any(
            p_name == tc_item.get("name")
            and {k: v for k, v in p_args.items() if k != "request_id"} == tc_norm
            for p_name, p_args in past_executions
        )
        if not already_ran:
            filtered_calls.append(tc_item)
            meta_item["index"] = len(filtered_meta) + 1
            filtered_meta.append(meta_item)
    return filtered_calls, filtered_meta


async def expand_full_action_plan_with_llm(
    model: BaseChatModel,
    prompt: str,
    initial_tool_calls: list[ToolCall],
    registry: CapabilityRegistry,
    past_executions: list[tuple[Any, dict[str, Any]]] | None = None,
    locale: str = "es",
) -> tuple[list[ToolCall], list[dict[str, Any]]]:
    """Expande mediante el LLM la secuencia completa de etapas del plan antes de pausar en HITL."""
    if not prompt or not initial_tool_calls:
        return initial_tool_calls, []

    prompt_mgr = get_prompt_manager()
    registered_tools = {t.name: t for t in registry.list_tools()}
    has_mut_registry = any(
        not getattr(t, "read_only", True) or t.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        for t in registered_tools.values()
    )
    if not has_mut_registry:
        return initial_tool_calls, []

    if not _has_mutative_actions(prompt, initial_tool_calls, registered_tools, locale):
        return initial_tool_calls, []

    catalog_text = _build_planning_catalog(registry)
    first_call = initial_tool_calls[0]
    sys_content = prompt_mgr.render("hitl_planning", locale=locale, tools_catalog_text=catalog_text)
    human_content = prompt_mgr.render(
        "hitl_human",
        locale=locale,
        prompt=prompt,
        first_call_json=json.dumps(
            {"name": first_call.get("name"), "args": first_call.get("args")}, ensure_ascii=False
        ),
    )

    planning_messages: list[BaseMessage] = [
        SystemMessage(content=sys_content),
        HumanMessage(content=human_content),
    ]

    try:
        res = await model.ainvoke(planning_messages)
    except NotImplementedError:
        res = model.invoke(planning_messages)

    raw_text = str(getattr(res, "content", res)).strip()
    calls, meta = _parse_planning_response(raw_text, registered_tools)

    if calls and any(m.get("mutative") for m in meta):
        if past_executions:
            filtered_calls, filtered_meta = _filter_past_executions(calls, meta, past_executions)
            if filtered_calls:
                return filtered_calls, filtered_meta
        return calls, meta

    return initial_tool_calls, []
