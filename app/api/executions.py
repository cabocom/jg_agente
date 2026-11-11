# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Controlador REST y adaptador HTTP para el ciclo de vida de ejecuciones cognitivas."""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.db.exceptions import PersistenceError
from app.db.session import get_async_session
from app.models.io import (
    AgentInput,
    AgentOutput,
    ExecutionStatus,
    ExecutionThreadDetail,
    HITLResolutionRequest,
    PersistenceMetadata,
    PersistenceStatus,
)
from app.security.auth import verify_control_plane_auth
from app.services.background_execution_service import (
    run_in_background,
)
from app.services.execution_notification_service import (
    get_agent_credentials as _get_agent_credentials,
)
from app.services.execution_notification_service import (
    notify_execution_completion,
)
from app.services.execution_orchestrator import (
    execute_graph_pipeline,
    get_agent_graph,
)
from app.services.execution_persistence_service import (
    persist_or_update_execution as _persist_or_update_execution,
)
from app.services.execution_persistence_service import (
    persist_with_retry as _persist_with_retry,
)
from app.services.execution_persistence_service import (
    spool_emergency_execution as _spool_emergency_execution,
)
from app.services.execution_query_service import (
    get_execution_thread_detail,
)
from app.services.hitl_resume_service import (
    resolve_hitl_execution as _resolve_hitl_execution,
)

logger = logging.getLogger("jg_agente.api.executions")

router = APIRouter(
    prefix="/executions",
    tags=["Executions"],
    dependencies=[Depends(verify_control_plane_auth)],
)


def _sync_correlation_id(input_data: AgentInput) -> str | None:
    """Sincroniza el correlation_id entre el contexto de traza y el payload."""
    cid = (
        get_correlation_id()
        or input_data.correlation_id
        or (
            input_data.metadata.get("correlation_id")
            if isinstance(input_data.metadata, dict)
            else None
        )
    )
    if cid:
        input_data.correlation_id = cid
        if "correlation_id" not in input_data.metadata:
            input_data.metadata["correlation_id"] = cid
    return cid


async def _record_initial_state(input_data: AgentInput) -> None:
    """Registra el estado inicial de la ejecución en base de datos o spool de emergencia."""
    try:
        await _persist_with_retry(
            input_data=input_data,
            status_val=ExecutionStatus.IN_PROGRESS.value,
        )
        input_data.metadata["persistence"] = PersistenceMetadata(
            status=PersistenceStatus.PERSISTED,
            persisted=True,
        ).model_dump()
    except (PersistenceError, Exception) as p_err:
        _spool_emergency_execution(input_data.execution_id, input_data.model_dump(mode="json"))
        logger.error(
            "Fallo de persistencia al registrar inicio de ejecución '%s': %s",
            input_data.execution_id,
            p_err,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo crítico de persistencia al registrar ejecución '{input_data.execution_id}'.",
        ) from p_err


@router.post(
    "/trigger",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Disparar o continuar la ejecución del grafo cognitivo",
    description="Inicia o continúa la ejecución del grafo LangGraph de forma síncrona o asíncrona.",
    responses={
        200: {"description": "Ejecución completada o pausada en espera de HITL."},
        202: {"description": "Ejecución encolada en segundo plano."},
        422: {"description": "Payload no válido."},
    },
)
async def trigger_execution(
    input_data: AgentInput,
    request: Request,
    background_tasks: BackgroundTasks,
    sync: bool = Query(default=True, description="Si es False, responde HTTP 202 Accepted."),
    graph: Any = Depends(get_agent_graph),
) -> Any:
    """Punto de entrada principal para la ejecución de agentes en jg_agente."""
    cid = _sync_correlation_id(input_data)
    await _record_initial_state(input_data)

    async_requested = (
        not sync
        or bool(input_data.parameters.get("async"))
        or bool(input_data.parameters.get("background"))
    )
    if async_requested:
        background_tasks.add_task(run_in_background, graph, input_data)
        accepted_output = AgentOutput(
            execution_id=input_data.execution_id,
            thread_id=input_data.thread_id,
            correlation_id=cid,
            status=ExecutionStatus.IN_PROGRESS,
            response="Ejecución aceptada y encolada en segundo plano.",
            metadata=input_data.metadata,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=accepted_output.model_dump(mode="json"),
        )

    return await execute_graph_pipeline(graph, input_data)


@router.get(
    "/{thread_id}",
    response_model=ExecutionThreadDetail,
    status_code=status.HTTP_200_OK,
    summary="Consultar estado de una ejecución por thread_id",
    description="Recupera el estado actual, historial y checkpoints del hilo de ejecución.",
    responses={
        200: {"description": "Detalle del hilo recuperado con éxito."},
        404: {"description": "Hilo de ejecución no encontrado."},
    },
)
async def get_execution_by_thread_id(
    thread_id: str,
    graph: Any = Depends(get_agent_graph),
    db: AsyncSession = Depends(get_async_session),
) -> ExecutionThreadDetail:
    """Consulta el estado, historial y checkpoints de un hilo de ejecución."""
    return await get_execution_thread_detail(thread_id=thread_id, graph=graph, db=db)


@router.post(
    "/{thread_id}/approve",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Aprobar ejecución pausada en HITL por thread_id",
    description="Reanuda la ejecución del grafo tras autorización humana.",
)
async def approve_execution_by_thread_id(
    thread_id: str,
    payload: HITLResolutionRequest | None = None,
    graph: Any = Depends(get_agent_graph),
) -> AgentOutput:
    """Reanuda el grafo en el paso de ejecución con aprobación del operador."""
    return await _resolve_hitl_execution(
        thread_id=thread_id,
        approved=True,
        payload=payload or HITLResolutionRequest(),
        graph=graph,
    )


@router.post(
    "/{thread_id}/reject",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Rechazar ejecución pausada en HITL por thread_id",
    description="Cancela la ejecución del grafo tras rechazo humano.",
)
async def reject_execution_by_thread_id(
    thread_id: str,
    payload: HITLResolutionRequest | None = None,
    graph: Any = Depends(get_agent_graph),
) -> AgentOutput:
    """Cancela el plan y concluye el grafo con estado cancelled."""
    return await _resolve_hitl_execution(
        thread_id=thread_id,
        approved=False,
        payload=payload or HITLResolutionRequest(),
        graph=graph,
    )


@router.post(
    "/approve",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Aprobar ejecución pausada en HITL (payload con thread_id)",
)
async def approve_execution(
    payload: HITLResolutionRequest,
    graph: Any = Depends(get_agent_graph),
) -> AgentOutput:
    """Endpoint alternativo para aprobar indicando thread_id en el payload JSON."""
    if not payload.thread_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El campo 'thread_id' es obligatorio en el payload para POST /executions/approve.",
        )
    return await _resolve_hitl_execution(
        thread_id=payload.thread_id,
        approved=True,
        payload=payload,
        graph=graph,
    )


@router.post(
    "/reject",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Rechazar ejecución pausada en HITL (payload con thread_id)",
)
async def reject_execution(
    payload: HITLResolutionRequest,
    graph: Any = Depends(get_agent_graph),
) -> AgentOutput:
    """Endpoint alternativo para rechazar indicando thread_id en el payload JSON."""
    if not payload.thread_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El campo 'thread_id' es obligatorio en el payload para POST /executions/reject.",
        )
    return await _resolve_hitl_execution(
        thread_id=payload.thread_id,
        approved=False,
        payload=payload,
        graph=graph,
    )


__all__ = [
    "_get_agent_credentials",
    "_persist_or_update_execution",
    "_persist_with_retry",
    "_resolve_hitl_execution",
    "_spool_emergency_execution",
    "approve_execution",
    "approve_execution_by_thread_id",
    "execute_graph_pipeline",
    "get_agent_graph",
    "get_execution_by_thread_id",
    "notify_execution_completion",
    "reject_execution",
    "reject_execution_by_thread_id",
    "router",
    "run_in_background",
    "trigger_execution",
]
