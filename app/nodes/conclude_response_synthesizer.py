# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Síntesis de la respuesta textual final en el nodo conclude."""

import re
from typing import Any

from langchain_core.messages import AIMessage

from app.models.state import AgentState, IntentModel, StepStatus


def _detect_meta_commentary(text: str) -> bool:
    """Detecta si un texto contiene meta-comentarios sobre herramientas internas."""
    patterns = [
        r"^(?:la\s+respuesta|el\s+resultado)\s+del?\s+(?:tool|herramienta)\b",
        r"^(?:el\s+tool|la\s+herramienta)\s+[\w:_-]+\s+(?:indica|muestra|devolvió|devuelve|ha\s+devuelto)\b",
        r"\bcumpliendo\s+(?:con\s+)?la\s+solicitud\b",
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def sanitize_for_short_answer(text: str) -> str:
    """Adapta el texto para modalidad de respuesta corta: elimina URLs, citas de fuentes y markdown."""
    if not text:
        return ""
    # 1. Eliminar URLs completas
    cleaned = re.sub(r"https?://\S+", "", text)
    # 2. Transformar enlaces markdown [texto](url) -> texto
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    # 3. Eliminar citaciones de fuentes tipo 'Fuente: ...' o '(Fuente: ...)'
    cleaned = re.sub(
        r"(?i)\(?(?:fuente|fuentes|disponible en|según datos de)\s*:\s*[^\n.)]*\)?", "", cleaned
    )
    # 4. Eliminar símbolos markdown
    cleaned = re.sub(r"[*_#`~]+", "", cleaned)
    cleaned = re.sub(r"^\s*[-•*]\s+", "", cleaned, flags=re.MULTILINE)
    # 5. Normalizar espacios
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def sanitize_for_voice_tts(text: str) -> str:
    """Alias retrocompatible para sanitize_for_short_answer."""
    return sanitize_for_short_answer(text)


def _find_clean_tool_output(records: list[Any]) -> str | None:
    """Busca en orden inverso la última salida textual limpia de una herramienta."""
    for rec in reversed(records):
        out = getattr(rec, "output", None)
        if isinstance(out, str) and out.strip():
            out_str = out.strip()
            if not (
                (out_str.startswith("{") and out_str.endswith("}"))
                or (out_str.startswith("[") and out_str.endswith("]"))
            ):
                return out_str
    return None


def _synthesize_tool_execution_output(records: list[Any], is_failed: bool) -> str:
    """Sintetiza la respuesta a partir de los registros de herramientas ejecutadas."""
    if is_failed:
        failed = [r for r in records if getattr(r, "status", None) == StepStatus.FAILED]
        err_msg = (
            failed[0].error if (failed and failed[0].error) else "Fallo en verificación u operación"
        )
        return f"La ejecución falló durante el paso '{failed[0].step_id}' ({failed[0].tool_name}): {err_msg}"

    clean_str_outputs = [
        str(r.output).strip()
        for r in records
        if isinstance(getattr(r, "output", None), str)
        and getattr(r, "output", "").strip()
        and not (
            getattr(r, "output", "").strip().startswith(("{", "["))
            and getattr(r, "output", "").strip().endswith(("}", "]"))
        )
    ]
    if len(records) == 1 and clean_str_outputs:
        return clean_str_outputs[0]

    tools_summary = ", ".join(getattr(r, "tool_name", "tool") for r in records)
    return (
        f"Herramientas ejecutadas con éxito. Se completaron satisfactoriamente las "
        f"operaciones solicitadas mediante: {tools_summary}."
    )


def synthesize_final_response(
    state: AgentState,
    is_cancelled: bool,
    is_rejected: bool,
    is_failed: bool,
    is_resolved: bool,
    is_iteration_limit_reached: bool,
    records: list[Any],
    errors: list[Any],
    last_eval: Any,
    approval_val: Any,
    max_iterations: int,
) -> str:
    """Determina la respuesta textual final aplicando formateo de respuesta corta si se solicita."""
    raw_res = _resolve_raw_final_response(
        state=state,
        is_cancelled=is_cancelled,
        is_rejected=is_rejected,
        is_failed=is_failed,
        is_resolved=is_resolved,
        is_iteration_limit_reached=is_iteration_limit_reached,
        records=records,
        errors=errors,
        last_eval=last_eval,
        approval_val=approval_val,
        max_iterations=max_iterations,
    )
    from app.nodes.reason_context import is_short_answer_request

    if is_short_answer_request(state):
        return sanitize_for_short_answer(raw_res)
    return raw_res


def _resolve_hitl_or_failure_response(
    state: AgentState,
    is_cancelled: bool,
    is_rejected: bool,
    is_failed: bool,
    approval_val: Any,
    records: list[Any],
    errors: list[Any],
) -> str | None:
    """Resuelve la respuesta ante cancelación de HITL o fallo operacional."""
    if is_cancelled or is_rejected:
        notes = (
            getattr(approval_val, "notes", None)
            if approval_val
            else (approval_val.get("notes") if isinstance(approval_val, dict) else None)
        )
        return str(notes or "Ejecución cancelada por rechazo de operador (HITL).")
    rollback_recs = list(state.get("rollback_records") or [])
    if is_failed and rollback_recs:
        return (
            f"La ejecución falló durante la verificación. Se ejecutó la compensación automática (rollback) "
            f"de {len(rollback_recs)} paso(s) reversible(s)."
        )
    if is_failed:
        failed_steps = [r for r in records if getattr(r, "status", None) == StepStatus.FAILED]
        if failed_steps:
            err_msg = failed_steps[0].error or "Fallo en verificación u operación"
            return f"La ejecución falló durante el paso '{failed_steps[0].step_id}' ({failed_steps[0].tool_name}): {err_msg}"
        if errors:
            return f"La ejecución falló con error: {errors[-1].message}"
    return None


def _resolve_evaluation_response(
    last_eval: Any,
    is_iteration_limit_reached: bool,
    max_iterations: int,
    records: list[Any],
) -> str | None:
    """Resuelve la respuesta derivada de la evaluación semántica cognitivo-adaptativa."""
    if not last_eval:
        return None
    exp = getattr(last_eval, "explanation", None) or (
        last_eval.get("explanation") if isinstance(last_eval, dict) else None
    )
    if not exp or not str(exp).strip():
        return None
    candidate = str(exp).strip()
    if is_iteration_limit_reached:
        clean_exp = candidate.rstrip(".")
        executed_tools = [r.tool_name for r in records if getattr(r, "tool_name", None)]
        unique_tools = list(dict.fromkeys(executed_tools))
        tools_info = f" (tras consultar: {', '.join(unique_tools)})" if unique_tools else ""
        return (
            f"He avanzado hasta el siguiente punto{tools_info}: {clean_exp}.\n\n"
            f"No he podido continuar procesando más detalles porque el agente está programado para no exceder un límite de seguridad de "
            f"{max_iterations} iteraciones consecutivas. "
            f"Te sugiero formular una consulta más acotada o específica para obtener el dato restante directamente."
        )
    if _detect_meta_commentary(candidate) and records:
        clean_tool_output = _find_clean_tool_output(records)
        return clean_tool_output or candidate
    return candidate


def _resolve_message_or_intent_response(
    state: AgentState,
    is_failed: bool,
    records: list[Any],
    errors: list[Any],
    is_resolved: bool,
) -> str:
    """Extrae la respuesta textual de AIMessages, IntentModel o ejecuciones previas."""
    messages = list(state.get("messages") or [])
    if not is_failed:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                c_str = str(msg.content).strip()
                if c_str and not (c_str.startswith("{") and c_str.endswith("}")):
                    return c_str
    intent_val = state.get("intent")
    if isinstance(intent_val, IntentModel) and intent_val.parameters:
        resp = intent_val.parameters.get("response")
        if resp:
            return str(resp).strip()
    elif isinstance(intent_val, dict):
        resp = intent_val.get("parameters", {}).get("response")
        if resp:
            return str(resp).strip()
    if records:
        return _synthesize_tool_execution_output(records, is_failed)
    if errors:
        return f"La ejecución finalizó con error: {errors[-1].message}"
    return "Ejecución finalizada con éxito." if is_resolved else "Ejecución concluida con errores."


def _resolve_raw_final_response(
    state: AgentState,
    is_cancelled: bool,
    is_rejected: bool,
    is_failed: bool,
    is_resolved: bool,
    is_iteration_limit_reached: bool,
    records: list[Any],
    errors: list[Any],
    last_eval: Any,
    approval_val: Any,
    max_iterations: int,
) -> str:
    """Determina la respuesta textual final siguiendo la jerarquía de precedencia del agente."""
    hitl_res = _resolve_hitl_or_failure_response(
        state, is_cancelled, is_rejected, is_failed, approval_val, records, errors
    )
    if hitl_res is not None:
        return hitl_res

    eval_res = _resolve_evaluation_response(
        last_eval, is_iteration_limit_reached, max_iterations, records
    )
    if eval_res is not None:
        return eval_res

    return _resolve_message_or_intent_response(state, is_failed, records, errors, is_resolved)
