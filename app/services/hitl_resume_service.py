# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de reanudación y resolución humana en el bucle (HITL) para flujos pausados."""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from langgraph.errors import GraphInterrupt
from langgraph.types import Command

from app.db.exceptions import PersistenceError
from app.models.io import (
    AgentInput,
    AgentOutput,
    ExecutionStatus,
    HITLResolutionRequest,
    PersistenceMetadata,
    PersistenceStatus,
)
from app.models.state import ApprovalStatus

logger = logging.getLogger("jg_agente.services.hitl")


def _validate_snapshot_for_resume(state_snapshot: Any, thread_id: str) -> list[str]:
    """Verifica que el snapshot de LangGraph sea apto para recibir una resolución HITL."""
    if not state_snapshot or not getattr(state_snapshot, "values", None):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hilo de ejecución '{thread_id}' no encontrado en el checkpointer.",
        )

    next_nodes: list[str] = (
        list(state_snapshot.next) if getattr(state_snapshot, "next", None) else []
    )
    if not next_nodes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El hilo de ejecución '{thread_id}' ya ha finalizado y no requiere aprobación.",
        )

    if "human_approval" not in next_nodes and not getattr(state_snapshot, "tasks", None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El hilo de ejecución '{thread_id}' no se encuentra en estado de espera de aprobación "
                f"(nodos siguientes: {next_nodes})."
            ),
        )
    return next_nodes


def _build_resume_command(approved: bool, payload: HITLResolutionRequest) -> Command[Any]:
    """Construye el Command de LangGraph con los metadatos de aprobación/rechazo."""
    resume_payload: dict[str, Any] = {
        "approved": approved,
        "status": ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value,
        "approver": payload.approver,
        "notes": payload.notes
        or ("Aprobado por operador" if approved else "Rechazado por operador"),
        "action": "approve" if approved else "reject",
    }
    return Command(resume=resume_payload)


def _format_hitl_output(
    final_state: dict[str, Any],
    thread_id: str,
    approved: bool,
    payload: HITLResolutionRequest,
    elapsed_ms: float,
) -> AgentOutput:
    """Construye y normaliza el objeto AgentOutput tras la resolución HITL."""
    raw_output = final_state.get("output")
    if isinstance(raw_output, AgentOutput):
        agent_output = raw_output
    elif isinstance(raw_output, dict):
        agent_output = AgentOutput(**raw_output)
    else:
        req_obj = final_state.get("request")
        exec_id = getattr(req_obj, "execution_id", "exec-resumed") if req_obj else "exec-resumed"
        out_status = ExecutionStatus.COMPLETED if approved else ExecutionStatus.CANCELLED
        agent_output = AgentOutput(
            execution_id=exec_id,
            thread_id=thread_id,
            status=out_status,
            response=payload.notes
            or (
                "Ejecución completada tras aprobación."
                if approved
                else "Ejecución cancelada por rechazo de operador (HITL)."
            ),
            execution_time_ms=elapsed_ms,
            requires_approval=False,
            pending_approval_id=None,
            completed_at=datetime.now(UTC),
        )

    agent_output.requires_approval = False
    agent_output.pending_approval_id = None
    if agent_output.data is None:
        agent_output.data = {}

    formatted_steps = []
    for s in final_state.get("cognitive_steps") or []:
        s_dict = s.model_dump(mode="json") if hasattr(s, "model_dump") else dict(s)
        if s_dict.get("status") == "waiting_approval":
            s_dict["status"] = "completed" if approved else "failed"
        formatted_steps.append(s_dict)
    agent_output.data["cognitive_steps"] = formatted_steps
    agent_output.data["steps"] = formatted_steps

    if not approved:
        agent_output.status = ExecutionStatus.CANCELLED
        rejection_text = (
            payload.notes
            or getattr(payload, "justification", None)
            or getattr(payload, "reason", None)
        )
        if rejection_text:
            agent_output.response = rejection_text
        elif not agent_output.response or agent_output.response.startswith("Ejecución finalizada"):
            agent_output.response = "Ejecución cancelada por rechazo de operador (HITL)."

    return agent_output


async def _persist_hitl_resolution(
    agent_output: AgentOutput,
    thread_id: str,
    final_state: dict[str, Any],
) -> None:
    """Persiste el estado de resolución en la base de datos con respaldo de emergencia."""
    from app.api import executions as executions_api
    from app.services.execution_persistence_service import (
        persist_with_retry,
        spool_emergency_execution,
    )

    req_data = final_state.get("request")
    dummy_input = AgentInput(
        execution_id=agent_output.execution_id,
        thread_id=thread_id,
        prompt=getattr(req_data, "prompt", "HITL Decision") if req_data else "HITL Decision",
    )
    persist_fn = getattr(executions_api, "_persist_with_retry", persist_with_retry)
    spool_fn = getattr(executions_api, "_spool_emergency_execution", spool_emergency_execution)

    try:
        await persist_fn(
            input_data=dummy_input,
            status_val=agent_output.status.value,
            response_text=agent_output.response,
            data_payload=agent_output.data,
            execution_time_ms=agent_output.execution_time_ms,
            requires_approval=False,
            pending_approval_id=None,
            completed_at=datetime.now(UTC),
        )
        agent_output.metadata["persistence"] = PersistenceMetadata(
            status=PersistenceStatus.PERSISTED,
            persisted=True,
        ).model_dump()
    except (PersistenceError, Exception) as db_err:
        spool_fn(agent_output.execution_id, agent_output.model_dump(mode="json"))
        logger.error(
            "Fallo irrecuperable de persistencia al actualizar resolución HITL en '%s': %s",
            agent_output.execution_id,
            db_err,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo crítico de persistencia al actualizar resolución HITL para '{agent_output.execution_id}'.",
        ) from db_err


async def resolve_hitl_execution(
    thread_id: str,
    approved: bool,
    payload: HITLResolutionRequest,
    graph: Any,
) -> AgentOutput:
    """Reanuda o cancela una ejecución detenida en human_approval mediante Command(resume=...)."""
    config = {"configurable": {"thread_id": thread_id}}
    state_snapshot: Any = None
    try:
        state_snapshot = await graph.aget_state(config)
    except Exception as exc:
        logger.warning("Error al consultar checkpointer para thread '%s': %s", thread_id, exc)

    _validate_snapshot_for_resume(state_snapshot, thread_id)
    command = _build_resume_command(approved, payload)

    start_time = time.perf_counter()
    try:
        final_state = await graph.ainvoke(command, config=config)
    except GraphInterrupt:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        exec_id = (
            state_snapshot.values.get("request", {}).execution_id
            if hasattr(state_snapshot.values.get("request"), "execution_id")
            else "exec-hitl"
        )
        return AgentOutput(
            execution_id=str(exec_id),
            thread_id=thread_id,
            status=ExecutionStatus.WAITING_APPROVAL,
            response="Pausa HITL subsiguiente activada.",
            execution_time_ms=elapsed_ms,
            requires_approval=True,
            pending_approval_id="human_approval_required",
            completed_at=datetime.now(UTC),
        )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    agent_output = _format_hitl_output(final_state, thread_id, approved, payload, elapsed_ms)
    await _persist_hitl_resolution(agent_output, thread_id, final_state)
    return agent_output
