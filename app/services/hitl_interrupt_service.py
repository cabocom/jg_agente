# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de captura y procesamiento de interrupciones de seguridad HITL en LangGraph."""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.models.io import (
    AgentInput,
    AgentOutput,
    ExecutionStatus,
)
from app.services.execution_persistence_service import persist_execution_outcome

logger = logging.getLogger("jg_agente.services.hitl_interrupt")


async def recover_snapshot_steps(graph: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Recupera los saltos cognitivos previos acumulados en el checkpointer."""
    snapshot_steps: list[dict[str, Any]] = []
    try:
        state_snapshot = await graph.aget_state(config)
        if state_snapshot and state_snapshot.values:
            for step_item in state_snapshot.values.get("cognitive_steps") or []:
                if hasattr(step_item, "model_dump"):
                    snapshot_steps.append(step_item.model_dump(mode="json"))
                elif isinstance(step_item, dict):
                    snapshot_steps.append(step_item)
    except Exception as snap_err:
        logger.warning("No se pudo obtener snapshot en interrupción HITL: %s", snap_err)
    return snapshot_steps


def _build_approval_step(interrupt_value: Any) -> dict[str, Any]:
    """Genera la estructura de paso cognitivo correspondiente a la pausa HITL."""
    return {
        "step_id": f"cog_approval_{int(time.time() * 1000)}",
        "node": "human_approval",
        "title": "Control de Aprobación Humana (HITL)",
        "action": "Pausa de Seguridad Operacional",
        "description": "Operación de alto riesgo detenida. Requiere autorización humana.",
        "status": "waiting_approval",
        "details": interrupt_value if isinstance(interrupt_value, dict) else {},
        "duration_ms": 0.0,
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def _persist_hitl_pause_outcome(
    input_data: AgentInput,
    output: AgentOutput,
    failure_detail: str | None,
) -> None:
    """Persiste el estado de espera en BD con respaldo en disco si la base de datos no responde."""
    await persist_execution_outcome(
        input_data=input_data,
        agent_output=output,
        status_val=ExecutionStatus.WAITING_APPROVAL.value,
        failure_detail=failure_detail
        or f"Fallo crítico de persistencia en pausa HITL para '{input_data.execution_id}'.",
    )


async def handle_hitl_interrupt(
    graph: Any,
    config: dict[str, Any],
    input_data: AgentInput,
    thread_id: str,
    elapsed_ms: float,
    interrupt_value: Any,
    failure_detail: str | None = None,
) -> AgentOutput:
    """Procesa una pausa HITL originada por el nodo human_approval."""
    pending_id = (
        interrupt_value.get("action")
        if isinstance(interrupt_value, dict)
        else "human_approval_required"
    )
    message = (
        interrupt_value.get("message")
        if isinstance(interrupt_value, dict)
        else "Operación de alto riesgo requiere aprobación humana."
    )

    snapshot_steps = await recover_snapshot_steps(graph, config)
    snapshot_steps.append(_build_approval_step(interrupt_value))

    data_payload = (
        dict(interrupt_value)
        if isinstance(interrupt_value, dict)
        else {"details": str(interrupt_value)}
    )
    data_payload["cognitive_steps"] = snapshot_steps
    data_payload["steps"] = snapshot_steps

    output = AgentOutput(
        execution_id=input_data.execution_id,
        thread_id=thread_id,
        status=ExecutionStatus.WAITING_APPROVAL,
        response=str(message),
        data=data_payload,
        execution_time_ms=elapsed_ms,
        requires_approval=True,
        pending_approval_id=str(pending_id),
        metadata=input_data.metadata,
        completed_at=datetime.now(UTC),
    )
    detail = (
        failure_detail
        or f"Fallo crítico de persistencia en pausa HITL para '{input_data.execution_id}'."
    )
    await _persist_hitl_pause_outcome(input_data, output, detail)
    return output
