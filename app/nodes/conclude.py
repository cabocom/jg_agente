"""Nodo terminal de conclusión (conclude) para jg_agente.

Sintetiza la respuesta final del agente, unifica los resultados de ejecución,
calcula los tiempos de ciclo y construye el objeto de salida canónico AgentOutput
con status=completed (o failed) para finalizar el hilo en LangGraph.
"""

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage

from app.core.registry import CapabilityRegistry
from app.models.io import AgentOutput, ExecutionStatus
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalStatus,
    AuditRecord,
    CognitiveStepRecord,
    GoalStatus,
    IntentModel,
    StepStatus,
    VerificationStatus,
)

logger = logging.getLogger("jg_agente.nodes.conclude")


async def conclude_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Finaliza el ciclo del grafo consolidando la respuesta y generando AgentOutput.

    Args:
        state: Estado global actual del agente (AgentState).
        registry: Catálogo de capacidades opcional.

    Returns:
        Mutaciones de estado finales para LangGraph (status, is_resolved, output, messages, audit_trail).
    """
    req = state.get("request")
    execution_id = getattr(req, "execution_id", "exec-default") if req else "exec-default"
    thread_id = getattr(req, "thread_id", "thread-default") if req else "thread-default"

    errors = list(state.get("errors") or [])
    records = list(state.get("execution_records") or [])

    # 1. Determinar si la ejecución concluyó con éxito o fallo
    v_results = list(state.get("verification_results") or [])
    has_verification_fail = any(
        (v.get("status") if isinstance(v, dict) else getattr(v, "status", None))
        in (
            VerificationStatus.FAIL,
            VerificationStatus.FAIL.value,
            VerificationStatus.DEGRADED,
            VerificationStatus.DEGRADED.value,
        )
        for v in v_results
    )
    has_failed_records = any(getattr(r, "status", None) == StepStatus.FAILED for r in records)
    has_fatal_errors = any(getattr(e, "fatal", False) for e in errors)

    approval_val = state.get("approval")
    is_rejected = False
    if approval_val is not None:
        appr_status = getattr(approval_val, "status", None) or (
            approval_val.get("status") if isinstance(approval_val, dict) else None
        )
        is_rejected = appr_status in (
            ApprovalStatus.REJECTED,
            ApprovalStatus.REJECTED.value,
            "rejected",
        )

    is_cancelled = (
        state.get("status")
        in (AgentExecutionStatus.CANCELLED, AgentExecutionStatus.CANCELLED.value, "cancelled")
        or is_rejected
    )

    is_failed = (
        has_failed_records
        or has_fatal_errors
        or has_verification_fail
        or state.get("status") in (AgentExecutionStatus.FAILED, AgentExecutionStatus.ROLLING_BACK)
    )

    eval_records = list(state.get("evaluation_records") or [])
    last_eval = eval_records[-1] if eval_records else None
    goal_status = getattr(last_eval, "goal_status", None) if last_eval else None
    if goal_status is None and isinstance(last_eval, dict):
        goal_status = last_eval.get("goal_status")
    status_val = (
        goal_status.value
        if isinstance(goal_status, GoalStatus)
        else str(goal_status or "").lower().strip()
    )
    curr_iteration = int(state.get("iteration", 1))
    max_iterations = int(state.get("max_iterations", 3))
    is_iteration_limit_reached = curr_iteration >= max_iterations and status_val in (
        GoalStatus.NEEDS_MORE_INFO.value,
        "needs_more_info",
    )

    if is_cancelled:
        final_agent_status = AgentExecutionStatus.FAILED
        final_output_status = ExecutionStatus.CANCELLED
        is_resolved = False
    elif is_failed:
        final_agent_status = AgentExecutionStatus.FAILED
        final_output_status = ExecutionStatus.FAILED
        is_resolved = False
    elif is_iteration_limit_reached:
        final_agent_status = AgentExecutionStatus.FAILED
        final_output_status = ExecutionStatus.COMPLETED
        is_resolved = False
    else:
        final_agent_status = AgentExecutionStatus.RESOLVED
        final_output_status = ExecutionStatus.COMPLETED
        is_resolved = True

    # 2. Medición y cálculo de tiempos de ejecución (execution_time_ms)
    execution_time_ms: float = 0.0
    total_tool_ms = sum(getattr(r, "duration_ms", 0.0) for r in records)

    if req and getattr(req, "created_at", None):
        delta_ms = (datetime.now(UTC) - req.created_at).total_seconds() * 1000.0
        execution_time_ms = max(round(delta_ms, 2), round(total_tool_ms, 2), 0.0)
    elif records:
        execution_time_ms = max(0.0, round(total_tool_ms, 2))

    # 3. Extracción y síntesis de la respuesta textual final
    response_text = ""
    messages = list(state.get("messages") or [])

    # A. Si la ejecución fue rechazada/cancelada por HITL, la respuesta prioritaria es la justificación de rechazo
    if is_cancelled or is_rejected:
        rejection_notes = (
            getattr(approval_val, "notes", None)
            if approval_val
            else (approval_val.get("notes") if isinstance(approval_val, dict) else None)
        )
        response_text = str(
            rejection_notes or "Ejecución cancelada por rechazo de operador (HITL)."
        )

    # B. Sintetizar si hubo compensación automática (rollback)
    rollback_recs = list(state.get("rollback_records") or [])
    if not response_text and is_failed and rollback_recs:
        response_text = (
            f"La ejecución falló durante la verificación. Se ejecutó la compensación automática (rollback) "
            f"de {len(rollback_recs)} paso(s) reversible(s)."
        )

    # B2. Si la ejecución falló, priorizar reporte explícito de error para no enmascarar fallos con AIMessage previo
    if not response_text and is_failed:
        failed_steps = [r for r in records if getattr(r, "status", None) == StepStatus.FAILED]
        if failed_steps:
            err_msg = (
                failed_steps[0].error
                if failed_steps[0].error
                else "Fallo en verificación u operación"
            )
            response_text = f"La ejecución falló durante el paso '{failed_steps[0].step_id}' ({failed_steps[0].tool_name}): {err_msg}"
        elif errors:
            response_text = f"La ejecución falló con error: {errors[-1].message}"

    # C. Prioridad cognitiva: Evaluación semántica (EvaluationRecord)
    if not response_text and eval_records:
        explanation = getattr(last_eval, "explanation", None) or (
            last_eval.get("explanation") if isinstance(last_eval, dict) else None
        )
        if explanation and str(explanation).strip():
            candidate_text = str(explanation).strip()

            # Caso amigable: límite de iteraciones de seguridad alcanzado
            if is_iteration_limit_reached:
                clean_exp = candidate_text.rstrip(".")
                executed_tools = [r.tool_name for r in records if getattr(r, "tool_name", None)]
                unique_tools = list(dict.fromkeys(executed_tools))
                tools_info = f" (tras consultar: {', '.join(unique_tools)})" if unique_tools else ""
                response_text = (
                    f"He avanzado hasta el siguiente punto{tools_info}: {clean_exp}.\n\n"
                    f"No he podido continuar procesando más detalles porque el agente está programado para no exceder un límite de seguridad de "
                    f"{max_iterations} iteraciones consecutivas. "
                    f"Te sugiero formular una consulta más acotada o específica para obtener el dato restante directamente."
                )
            else:
                # Detección defensiva de meta-comentarios de auditoría (ej. "La respuesta del tool get_weather indica...")
                is_meta_comment = bool(
                    re.search(
                        r"^(?:la\s+respuesta|el\s+resultado)\s+del?\s+(?:tool|herramienta)\b",
                        candidate_text,
                        re.IGNORECASE,
                    )
                    or re.search(
                        r"^(?:el\s+tool|la\s+herramienta)\s+[\w:_-]+\s+(?:indica|muestra|devolvió|devuelve|ha\s+devuelto)\b",
                        candidate_text,
                        re.IGNORECASE,
                    )
                    or re.search(
                        r"\bcumpliendo\s+(?:con\s+)?la\s+solicitud\b",
                        candidate_text,
                        re.IGNORECASE,
                    )
                )
                # Si es un meta-comentario y tenemos una salida limpia en texto de la herramienta, preferir la salida directa
                if is_meta_comment and records:
                    clean_tool_output = None
                    for rec in reversed(records):
                        out = getattr(rec, "output", None)
                        if isinstance(out, str) and out.strip():
                            out_str = out.strip()
                            if not (
                                (out_str.startswith("{") and out_str.endswith("}"))
                                or (out_str.startswith("[") and out_str.endswith("]"))
                            ):
                                clean_tool_output = out_str
                                break
                    response_text = clean_tool_output or candidate_text
                else:
                    response_text = candidate_text

    # D. Buscar en el último AIMessage con contenido conversacional (evitando salidas crudas de tools)
    if not response_text:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                content_str = str(msg.content).strip()
                if content_str and not (content_str.startswith("{") and content_str.endswith("}")):
                    response_text = content_str
                    break

    # E. Buscar en los parámetros de la intención (intent)
    if not response_text:
        intent_val = state.get("intent")
        if isinstance(intent_val, IntentModel) and intent_val.parameters:
            resp = intent_val.parameters.get("response")
            if resp:
                response_text = str(resp).strip()
        elif isinstance(intent_val, dict):
            resp = intent_val.get("parameters", {}).get("response")
            if resp:
                response_text = str(resp).strip()

    # F. Sintetizar a partir de las herramientas ejecutadas (en lenguaje natural limpio, erradicando volcado JSON)
    if not response_text and records:
        if is_failed:
            failed_steps = [r for r in records if getattr(r, "status", None) == StepStatus.FAILED]
            err_msg = (
                failed_steps[0].error
                if failed_steps and failed_steps[0].error
                else "Fallo en verificación u operación"
            )
            response_text = f"La ejecución falló durante el paso '{failed_steps[0].step_id}' ({failed_steps[0].tool_name}): {err_msg}"
        else:
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
                response_text = clean_str_outputs[0]
            else:
                tools_summary = ", ".join(getattr(r, "tool_name", "tool") for r in records)
                response_text = f"Herramientas ejecutadas con éxito. Se completaron satisfactoriamente las operaciones solicitadas mediante: {tools_summary}."

    # G. Sintetizar a partir de los errores registrados
    if not response_text and errors:
        response_text = f"La ejecución finalizó con error: {errors[-1].message}"

    # F. Fallback canónico por defecto
    if not response_text:
        if is_cancelled:
            rejection_notes = (
                getattr(approval_val, "notes", None)
                if approval_val
                else (approval_val.get("notes") if isinstance(approval_val, dict) else None)
            )
            response_text = str(
                rejection_notes or "Ejecución cancelada por rechazo de operador (HITL)."
            )
        elif is_resolved:
            response_text = "Ejecución finalizada con éxito."
        else:
            response_text = "Ejecución concluida con errores."

    # Asegurar que el último mensaje del historial contenga la respuesta resolutiva
    if not messages or not isinstance(messages[-1], AIMessage) or not messages[-1].content:
        messages.append(AIMessage(content=response_text))

    # 4. Construcción de carga de datos (data) y metadatos
    data_payload: dict[str, Any] = {}
    if records:
        data_payload["steps_count"] = len(records)
        data_payload["execution_records"] = [
            r.model_dump(mode="json") if hasattr(r, "model_dump") else dict(r) for r in records
        ]

    # Consolidación de saltos cognitivos (Cognitive Steps Trace)
    cog_steps = list(state.get("cognitive_steps") or [])
    conclude_step = CognitiveStepRecord(
        step_id=f"cog_conclude_{int(time.time() * 1000)}",
        node="conclude",
        title="Síntesis y Cierre Cognitivo",
        action="Consolidación de Salida",
        description="El agente consolidó el resultado de todos los saltos previos y formuló la respuesta final.",
        status="completed" if is_resolved else "failed",
        details={
            "is_resolved": is_resolved,
            "final_status": final_output_status.value,
            "execution_time_ms": execution_time_ms,
            "response_preview": response_text[:300] if response_text else None,
        },
        duration_ms=0.0,
        timestamp=datetime.now(UTC),
    )
    cog_steps.append(conclude_step)

    data_payload["cognitive_steps"] = [
        s.model_dump(mode="json") if hasattr(s, "model_dump") else dict(s) for s in cog_steps
    ]
    data_payload["steps"] = data_payload["cognitive_steps"]

    if state.get("environment_snapshot"):
        data_payload["environment_snapshot"] = state.get("environment_snapshot")
    if state.get("verification_results"):
        data_payload["verification_results"] = state.get("verification_results")
    if state.get("rollback_records"):
        data_payload["rollback_records"] = state.get("rollback_records")

    metadata_payload: dict[str, Any] = {
        "is_resolved": is_resolved,
        "tools_executed_count": len(records),
        "cognitive_steps_count": len(cog_steps),
        "errors_count": len(errors),
    }

    # 5. Instanciar el objeto canónico de salida AgentOutput
    agent_output = AgentOutput(
        execution_id=execution_id,
        thread_id=thread_id,
        status=final_output_status,
        response=response_text,
        data=data_payload if data_payload else None,
        execution_time_ms=execution_time_ms,
        requires_approval=bool(state.get("human_intervention_required")),
        error=errors[-1].message if (is_failed and errors) else None,
        metadata=metadata_payload,
        completed_at=datetime.now(UTC),
    )

    logger.info(
        "[conclude_node] Concluyendo ejecución '%s' (status=%s, is_resolved=%s, time=%.2fms)",
        execution_id,
        final_output_status.value,
        is_resolved,
        execution_time_ms,
    )

    return {
        "status": final_agent_status,
        "is_resolved": is_resolved,
        "output": agent_output,
        "messages": messages,
        "cognitive_steps": [conclude_step],
        "audit_trail": [
            AuditRecord(
                event_type="execution_concluded",
                actor="conclude_node",
                details={
                    "final_status": final_output_status.value,
                    "agent_status": final_agent_status.value,
                    "is_resolved": is_resolved,
                    "execution_time_ms": execution_time_ms,
                    "steps_count": len(records),
                    "cognitive_steps_count": len(cog_steps),
                    "errors_count": len(errors),
                },
                timestamp=datetime.now(UTC),
            )
        ],
    }
