"""Nodo cognitivo de evaluación semántica y Capability-Awareness (evaluate) para jg_agente.

Evalúa si la evidencia recopilada tras la ejecución de herramientas responde de forma
completa al objetivo del usuario o si se requieren acciones adicionales.
Incorpora capability-awareness: si detecta una anomalía o necesidad técnica ausente
en el catálogo de herramientas disponibles (ej. requerir docker:logs cuando no existe),
emite GoalStatus.BLOCKED_MISSING_CAPABILITY y formula una explicación proactiva.
"""

import json
import logging
import re
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

logger = logging.getLogger("jg_agente.nodes.evaluate")

JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")


def _extract_json(text: str) -> dict[str, Any] | None:
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
        # Búsqueda defensiva del primer par de llaves {}
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


async def evaluate_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Evalúa semánticamente el estado del objetivo y la suficiencia de la evidencia técnica.

    Args:
        state: Estado global actual del grafo (AgentState).
        registry: Catálogo de capacidades para verificar herramientas disponibles.
        llm: Instancia opcional de BaseChatModel (si es None, se resuelve vía get_chat_model()).

    Returns:
        Diccionario con las mutaciones de estado para LangGraph (evaluation_records,
        cognitive_steps, audit_trail, is_resolved).
    """
    start_time = time.perf_counter()
    iteration = int(state.get("iteration", 1))

    # 1. Recuperar contexto original del usuario y evidencia técnica
    prompt = ""
    req = state.get("request")
    if req and req.prompt:
        prompt = req.prompt.strip()

    # Catálogo de herramientas registradas disponibles
    available_tools = [
        {"name": t.name, "description": t.description, "category": t.category}
        for t in registry.list_tools()
    ]
    tool_names_available = {t["name"] for t in available_tools}

    # Evidencia técnica de herramientas ejecutadas
    exec_records = state.get("execution_records") or []
    tool_messages: list[str] = []
    for msg in state.get("messages") or []:
        if isinstance(msg, ToolMessage):
            raw_c = str(msg.content or "")
            capped_c = (
                raw_c[:2500] + "\n... [observación truncada a 2500 chars para evaluación]"
                if len(raw_c) > 2500
                else raw_c
            )
            tool_messages.append(f"[{msg.name or 'Tool'}]: {capped_c}")

    # Fallos o errores reportados en el estado
    errors = state.get("errors") or []
    error_summaries = [f"[{e.code}]: {e.message}" for e in errors]

    # 2. Construir System Prompt evaluador con Capability-Awareness y control de verbosidad
    verbosity = getattr(settings, "AGENT_VERBOSITY", "concise").lower().strip()
    if verbosity == "concise":
        style_instructions = (
            "DIRECTIVAS ESTRICTAS DE ESTILO Y CONCISIÓN (OBLIGATORIO):\n"
            "- Sé DIRECTO, EJECUTIVO y CONCISO (máximo 1 o 2 frases breves).\n"
            "- PROHIBIDO TERMINANTEMENTE hablar en tercera persona sobre las herramientas o su ejecución "
            "(ej. NUNCA digas 'La respuesta del tool X indica...', 'El tool X devolvió...', 'Se cumplió la solicitud del usuario').\n"
            "- PROHIBIDO hacer meta-comentarios sobre la formulación de la pregunta del usuario "
            "(ej. NO digas 'lo que responde a la primera parte del objetivo del usuario', 'según la solicitud', etc.).\n"
            "- PROHIBIDO hablar de procesos internos o catálogos abstractos con rodeos "
            "(ej. en lugar de 'En el catálogo de herramientas disponible no existe ninguna herramienta para...', "
            "sé directo: 'Todos los contenedores están en ejecución. No está disponible la herramienta para inspeccionar logs.').\n"
            "- Comunica el estado real, los datos sustantivos y las conclusiones operativas de manera tajante, "
            "directamente dirigida al usuario (ej. 'El clima actual en Alcobendas es de 20°C con cielo despejado').\n"
        )
    elif verbosity == "detailed":
        style_instructions = (
            "DIRECTIVAS DE ESTILO:\n"
            "- Proporciona un desglose detallado y paso a paso de los hallazgos técnicos para el operador.\n"
            "- PROHIBIDO hablar en tercera persona sobre las herramientas (NUNCA 'La respuesta del tool...'). "
            "Responde directamente con los datos y hechos averiguados.\n"
        )
    else:  # balanced
        style_instructions = (
            "DIRECTIVAS DE ESTILO:\n"
            "- Explica con claridad el estado del objetivo sin redundancias innecesarias.\n"
            "- PROHIBIDO hablar en tercera persona sobre las herramientas. Responde directamente con los datos averiguados.\n"
        )

    system_prompt = (
        "Eres el Evaluador Cognitivo y Síntesis de Objetivos de un sistema de agentes autónomos.\n"
        "Tu misión es evaluar si la evidencia técnica recopilada responde a la solicitud del usuario "
        "y generar en el campo 'explanation' la respuesta final en lenguaje natural que leerá el usuario humano.\n\n"
        f"{style_instructions}\n"
        "INSTRUCCIONES PARA 'explanation' SEGÚN 'goal_status':\n"
        "1. 'satisfied': Si la información técnica obtenida responde a la solicitud del usuario (por ejemplo, si solicitó logs, listados, métricas, estado de infraestructura o lectura de datos y las observaciones ya los contienen). "
        "En 'explanation', DEBES responder DIRECTAMENTE al usuario comunicando los datos concretos obtenidos "
        "(ej. si preguntó por el clima, indica el clima exacto y temperatura; si preguntó por servicios o logs, entrega los datos solicitados). "
        "PROHIBIDO TERMINANTEMENTE actuar como un auditor externo o hablar de las herramientas en tercera persona "
        "(NUNCA digas: 'La respuesta del tool indica...', 'El tool devolvió...', 'Cumpliendo la solicitud del usuario', etc.). "
        "Habla de tú a tú al usuario con la información final solicitada.\n"
        "2. 'needs_more_info': ÚNICAMENTE si para cumplir el objetivo del usuario se requiere de forma indispensable ejecutar una herramienta adicional o una nueva operación con parámetros complementarios (por ejemplo, leer el siguiente bloque de líneas, inspeccionar otro contenedor distinto o paginar) "
        "que SÍ está disponible en el catálogo de herramientas registradas. Explica qué dato concreto falta y qué se ejecutará.\n"
        "3. 'blocked_missing_capability': Si detectas un problema o si el usuario solicitó investigar algo "
        "pero la herramienta requerida NO EXISTE en el catálogo de herramientas registradas. "
        "Indica brevemente qué hallazgo real hay y qué herramienta o capacidad específica falta.\n"
        "4. 'failed': Si ocurrió un error irrecuperable que imposibilita continuar. Explica el motivo de forma clara.\n\n"
        "DEBES RESPONDER EXCLUSIVAMENTE CON UN OBJETO JSON con la siguiente estructura:\n"
        "{\n"
        '  "goal_status": "satisfied" | "needs_more_info" | "blocked_missing_capability" | "failed",\n'
        '  "explanation": "Respuesta directa y sustantiva en lenguaje natural para el usuario con los datos reales obtenidos, sin meta-comentarios sobre herramientas",\n'
        '  "missing_capabilities": ["nombre_herramienta_faltante"],\n'
        '  "suggested_next_action": "nombre_herramienta_sugerida_si_aplica_o_null"\n'
        "}"
    )

    user_payload = {
        "user_goal": prompt,
        "iteration": iteration,
        "available_tools": available_tools,
        "executed_steps": [
            {
                "tool": r.tool_name,
                "status": r.status,
                "output_preview": str(getattr(r, "output", ""))[:500],
                "error": getattr(r, "error", None),
            }
            for r in exec_records
        ],
        "tool_observations": tool_messages,
        "errors_detected": error_summaries,
    }

    user_message_content = (
        "Evalúa la siguiente evidencia contra el objetivo del usuario:\n"
        f"{json.dumps(user_payload, indent=2, ensure_ascii=False)}"
    )

    # 3. Invocar al modelo LLM
    model = llm or get_chat_model()
    messages_to_send = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message_content),
    ]

    goal_status = GoalStatus.SATISFIED
    explanation = "Objetivo procesado correctamente."
    missing_capabilities: list[str] = []
    suggested_next_action: str | None = None

    try:
        try:
            raw_res = await model.ainvoke(messages_to_send)
        except NotImplementedError:
            raw_res = model.invoke(messages_to_send)

        content = ""
        if isinstance(raw_res, AIMessage):
            content = str(raw_res.content)
        else:
            content = str(getattr(raw_res, "content", raw_res))

        parsed = _extract_json(content)
        if parsed and "goal_status" in parsed:
            raw_status = str(parsed.get("goal_status", "")).lower().strip()
            # Mapear estado
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
                "[evaluate_node] El LLM no devolvió un JSON estructurado válido: %s", content[:200]
            )
            explanation = content if content else "Evaluación completada."
            # Si hubo errores críticos en las herramientas, clasificar como failed
            if errors and any(getattr(e, "fatal", False) for e in errors):
                goal_status = GoalStatus.FAILED
    except Exception as exc:
        logger.error("[evaluate_node] Fallo invocando al evaluador LLM: %s", exc)
        explanation = f"Evaluación defensiva ante indisponibilidad del modelo evaluador: {exc}"
        goal_status = GoalStatus.FAILED if errors else GoalStatus.SATISFIED

    # 4. Validar consistencia de capability-awareness
    # Si se marcó needs_more_info pero la herramienta sugerida no existe en available_tools,
    # corregir automáticamente a BLOCKED_MISSING_CAPABILITY
    if (
        goal_status == GoalStatus.NEEDS_MORE_INFO
        and suggested_next_action
        and suggested_next_action not in tool_names_available
    ):
        logger.info(
            "[evaluate_node] La herramienta sugerida '%s' no está disponible en el catálogo. "
            "Cambiando estado a BLOCKED_MISSING_CAPABILITY.",
            suggested_next_action,
        )
        goal_status = GoalStatus.BLOCKED_MISSING_CAPABILITY
        if suggested_next_action not in missing_capabilities:
            missing_capabilities.append(suggested_next_action)

    duration_ms = max(0.0, round((time.perf_counter() - start_time) * 1000.0, 2))

    # 5. Construir registros estructurados
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
