# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo terminal de conclusión (conclude) para jg_agente.

Sintetiza la respuesta final del agente, unifica los resultados de ejecución,
calcula los tiempos de ciclo y construye el objeto de salida canónico AgentOutput
con status=completed (o failed) para finalizar el hilo en LangGraph.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage

from app.core.registry import CapabilityRegistry
from app.models.io import AgentOutput
from app.models.state import (
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
)
from app.nodes.conclude_payload_builder import (
    build_data_payload,
    evaluate_final_statuses,
)
from app.nodes.conclude_response_synthesizer import synthesize_final_response

logger = logging.getLogger("jg_agente.nodes.conclude")

__all__ = ["conclude_node"]


def _calculate_execution_time(req: Any, records: list[Any]) -> float:
    """Calcula la duración en milisegundos de la ejecución del agente."""
    total_tool_ms = float(sum(getattr(r, "duration_ms", 0.0) for r in records))
    if req and getattr(req, "created_at", None):
        delta_ms = (datetime.now(UTC) - req.created_at).total_seconds() * 1000.0
        return float(max(round(delta_ms, 2), round(total_tool_ms, 2), 0.0))
    if records:
        return float(max(0.0, round(total_tool_ms, 2)))
    return 0.0


async def conclude_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Finaliza el ciclo del grafo consolidando la respuesta y generando AgentOutput."""
    req = state.get("request")
    execution_id = getattr(req, "execution_id", "exec-default") if req else "exec-default"
    thread_id = getattr(req, "thread_id", "thread-default") if req else "thread-default"

    errors = list(state.get("errors") or [])
    records = list(state.get("execution_records") or [])
    approval_val = state.get("approval")
    max_iterations = int(state.get("max_iterations", 3))

    (
        is_cancelled,
        is_rejected,
        is_failed,
        is_resolved,
        is_limit_reached,
        final_agent_status,
        final_output_status,
        last_eval,
    ) = evaluate_final_statuses(state, records, errors)

    execution_time_ms = _calculate_execution_time(req, records)

    response_text = synthesize_final_response(
        state=state,
        is_cancelled=is_cancelled,
        is_rejected=is_rejected,
        is_failed=is_failed,
        is_resolved=is_resolved,
        is_iteration_limit_reached=is_limit_reached,
        records=records,
        errors=errors,
        last_eval=last_eval,
        approval_val=approval_val,
        max_iterations=max_iterations,
    )

    messages = list(state.get("messages") or [])
    if not messages or not isinstance(messages[-1], AIMessage) or not messages[-1].content:
        messages.append(AIMessage(content=response_text))

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

    data_payload = await build_data_payload(records, cog_steps, state)
    metadata_payload: dict[str, Any] = {
        "is_resolved": is_resolved,
        "tools_executed_count": len(records),
        "cognitive_steps_count": len(cog_steps),
        "errors_count": len(errors),
    }

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
