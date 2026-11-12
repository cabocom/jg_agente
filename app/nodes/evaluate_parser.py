# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Extracción y parseo de respuestas estructuradas del evaluador semántico."""

import json
import logging
import re
from typing import Any

from app.models.state import GoalStatus

logger = logging.getLogger("jg_agente.nodes.evaluate_parser")

JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


def extract_json(text: str) -> dict[str, Any] | None:
    """Extrae un objeto JSON válido desde una respuesta de texto o bloque Markdown."""
    cleaned = text.strip()
    match = JSON_BLOCK_PATTERN.search(cleaned)
    if match:
        cleaned = match.group(1).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                candidate = json.loads(cleaned[start : end + 1])
                if isinstance(candidate, dict):
                    return candidate
            except Exception:
                pass
    return None


def parse_evaluation_response(
    content: str,
    errors: list[Any],
    tool_names_available: set[str],
) -> tuple[GoalStatus, str, list[str], str | None]:
    """Parsea el contenido emitido por el LLM evaluador y aplica consistencia de capability-awareness."""
    goal_status = GoalStatus.SATISFIED
    explanation = "Objetivo procesado correctamente."
    missing_capabilities: list[str] = []
    suggested_next_action: str | None = None

    parsed = extract_json(content)
    if parsed and "goal_status" in parsed:
        raw_status = str(parsed.get("goal_status", "")).lower().strip()
        if raw_status in (GoalStatus.SATISFIED.value, "satisfied", "resolved"):
            goal_status = GoalStatus.SATISFIED
        elif raw_status in (GoalStatus.NEEDS_MORE_INFO.value, "needs_more_info"):
            goal_status = GoalStatus.NEEDS_MORE_INFO
        elif raw_status in (
            GoalStatus.BLOCKED_MISSING_CAPABILITY.value,
            "blocked_missing_capability",
            "missing_capability",
        ):
            goal_status = GoalStatus.BLOCKED_MISSING_CAPABILITY
        elif raw_status in (GoalStatus.FAILED.value, "failed"):
            goal_status = GoalStatus.FAILED
        else:
            goal_status = GoalStatus.SATISFIED

        explanation = str(parsed.get("explanation", explanation))
        raw_missing = parsed.get("missing_capabilities")
        if isinstance(raw_missing, list):
            missing_capabilities = [str(m) for m in raw_missing if m]
        suggested_next_action = parsed.get("suggested_next_action")
    else:
        logger.warning(
            "[evaluate_parser] El LLM no devolvió un JSON estructurado válido: %s", content[:200]
        )
        explanation = content if content else "Evaluación completada."
        if errors and any(getattr(e, "fatal", False) for e in errors):
            goal_status = GoalStatus.FAILED

    suggested_base = (
        str(suggested_next_action).strip().split()[0].rstrip(":,(") if suggested_next_action else ""
    )
    if (
        goal_status == GoalStatus.NEEDS_MORE_INFO
        and suggested_next_action
        and suggested_next_action not in tool_names_available
        and suggested_base not in tool_names_available
    ):
        logger.info(
            "[evaluate_parser] La herramienta sugerida '%s' no está en catálogo. Cambiando a BLOCKED_MISSING_CAPABILITY.",
            suggested_next_action,
        )
        goal_status = GoalStatus.BLOCKED_MISSING_CAPABILITY
        if suggested_next_action not in missing_capabilities:
            missing_capabilities.append(suggested_next_action)

    return goal_status, explanation, missing_capabilities, suggested_next_action
