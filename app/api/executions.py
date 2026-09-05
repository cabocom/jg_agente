"""Endpoints REST para el control y disparo de ejecuciones cognitivas en jg_agente."""

import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphInterrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.checkpointer import get_checkpointer
from app.core.graph import GraphBuilder
from app.core.llm import get_chat_model
from app.core.registry import CapabilityRegistry
from app.db.models import CoreExecution
from app.db.session import async_session_factory, get_async_session
from app.models.io import AgentInput, AgentOutput, ExecutionStatus
from app.models.state import AgentExecutionStatus, AgentState
from app.security.guard import SecurityGuard

logger = logging.getLogger("jg_agente.api.executions")

router = APIRouter(prefix="/executions", tags=["Executions"])


def get_agent_graph(request: Request) -> Any:
    """Obtiene o ensambla el grafo compilado del agente a partir de app.state."""
    app_state = request.app.state
    if hasattr(app_state, "agent_graph") and app_state.agent_graph is not None:
        return app_state.agent_graph

    registry: CapabilityRegistry = getattr(app_state, "registry", None) or CapabilityRegistry()
    checkpointer = getattr(app_state, "checkpointer", None) or get_checkpointer()
    llm = getattr(app_state, "llm", None) or get_chat_model()
    security_guard = getattr(app_state, "security_guard", None) or SecurityGuard()

    builder = GraphBuilder(
        registry=registry,
        llm=llm,
        security_guard=security_guard,
    )
    graph = builder.build(checkpointer=checkpointer)
    app_state.agent_graph = graph
    return graph


async def _persist_or_update_execution(
    db: AsyncSession,
    input_data: AgentInput,
    status_val: str = "in_progress",
    response_text: str | None = None,
    data_payload: dict[str, Any] | None = None,
    execution_time_ms: float = 0.0,
    requires_approval: bool = False,
    pending_approval_id: str | None = None,
    error_msg: str | None = None,
    completed_at: datetime | None = None,
) -> CoreExecution | None:
    """Crea o actualiza el registro de la ejecución en la tabla core_executions de forma segura y tolerante a fallos."""
    try:
        query = select(CoreExecution).where(CoreExecution.execution_id == input_data.execution_id)
        result = await db.execute(query)
        record = result.scalars().first()

        user_ctx_dict = (
            input_data.user_context.model_dump()
            if input_data.user_context and hasattr(input_data.user_context, "model_dump")
            else (input_data.user_context if isinstance(input_data.user_context, dict) else None)
        )

        if record is None:
            record = CoreExecution(
                execution_id=input_data.execution_id,
                thread_id=input_data.thread_id,
                status=status_val,
                prompt=input_data.prompt,
                response=response_text,
                parameters=input_data.parameters,
                data=data_payload,
                user_context=user_ctx_dict,
                execution_time_ms=execution_time_ms,
                requires_approval=requires_approval,
                pending_approval_id=pending_approval_id,
                error=error_msg,
                metadata_=input_data.metadata,
                created_at=input_data.created_at,
                completed_at=completed_at,
            )
            db.add(record)
        else:
            record.status = status_val
            if response_text is not None:
                record.response = response_text
            if data_payload is not None:
                record.data = data_payload
            if execution_time_ms > 0:
                record.execution_time_ms = execution_time_ms
            record.requires_approval = requires_approval
            if pending_approval_id is not None:
                record.pending_approval_id = pending_approval_id
            if error_msg is not None:
                record.error = error_msg
            if completed_at is not None:
                record.completed_at = completed_at

        await db.commit()
        await db.refresh(record)
        return record
    except Exception as exc:
        with contextlib.suppress(Exception):
            await db.rollback()
        logger.warning(
            "No se pudo persistir en core_executions (%s). Continuando en memoria: %s",
            input_data.execution_id,
            exc,
        )
        return None


async def execute_graph_pipeline(
    graph: Any,
    input_data: AgentInput,
) -> AgentOutput:
    """Ejecuta el ciclo del grafo LangGraph con captura de pausas HITL y finalización."""
    start_time = time.perf_counter()
    thread_id = input_data.thread_id
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "request": input_data,
        "messages": [HumanMessage(content=input_data.prompt)],
        "status": AgentExecutionStatus.OBSERVING,
        "current_step": 0,
        "retry_count": 0,
        "circuit_breaker_active": False,
        "human_intervention_required": False,
        "requires_approval": False,
        "is_resolved": False,
        "stop_reason": None,
        "errors": [],
        "execution_records": [],
        "audit_trail": [],
        "verification_results": [],
        "rollback_records": [],
    }

    try:
        # Ejecutar grafo síncronamente hasta END o interrupción
        final_state = await graph.ainvoke(initial_state, config=config)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # Si LangGraph retornó interrupción (HITL pause)
        if isinstance(final_state, dict) and "__interrupt__" in final_state:
            interrupt_items = final_state["__interrupt__"]
            interrupt_value = (
                interrupt_items[0].value
                if interrupt_items and hasattr(interrupt_items[0], "value")
                else (interrupt_items[0] if interrupt_items else {})
            )
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
            agent_output = AgentOutput(
                execution_id=input_data.execution_id,
                thread_id=thread_id,
                status=ExecutionStatus.WAITING_APPROVAL,
                response=str(message),
                data=interrupt_value
                if isinstance(interrupt_value, dict)
                else {"details": str(interrupt_value)},
                execution_time_ms=elapsed_ms,
                requires_approval=True,
                pending_approval_id=str(pending_id),
                metadata=input_data.metadata,
                completed_at=datetime.now(UTC),
            )
            try:
                async with async_session_factory() as db:
                    await _persist_or_update_execution(
                        db,
                        input_data=input_data,
                        status_val=ExecutionStatus.WAITING_APPROVAL.value,
                        response_text=agent_output.response,
                        data_payload=agent_output.data,
                        execution_time_ms=agent_output.execution_time_ms,
                        requires_approval=True,
                        pending_approval_id=agent_output.pending_approval_id,
                    )
            except Exception as db_err:
                logger.warning("Fallo al actualizar DB tras HITL pause: %s", db_err)

            return agent_output

        raw_output = final_state.get("output")
        if isinstance(raw_output, AgentOutput):
            agent_output = raw_output
        elif isinstance(raw_output, dict):
            agent_output = AgentOutput(**raw_output)
        else:
            is_resolved = final_state.get("is_resolved", True)
            agent_output = AgentOutput(
                execution_id=input_data.execution_id,
                thread_id=thread_id,
                status=ExecutionStatus.COMPLETED if is_resolved else ExecutionStatus.FAILED,
                response="Ejecución finalizada con éxito."
                if is_resolved
                else "Ejecución finalizada con fallos.",
                execution_time_ms=elapsed_ms,
                requires_approval=bool(final_state.get("human_intervention_required")),
                metadata=input_data.metadata,
                completed_at=datetime.now(UTC),
            )

        # Actualizar persistencia en DB si es posible
        try:
            async with async_session_factory() as db:
                await _persist_or_update_execution(
                    db,
                    input_data=input_data,
                    status_val=agent_output.status.value,
                    response_text=agent_output.response,
                    data_payload=agent_output.data,
                    execution_time_ms=agent_output.execution_time_ms,
                    requires_approval=agent_output.requires_approval,
                    pending_approval_id=agent_output.pending_approval_id,
                    error_msg=agent_output.error,
                    completed_at=agent_output.completed_at,
                )
        except Exception as db_err:
            logger.warning("Fallo al actualizar DB tras finalización: %s", db_err)

        return agent_output

    except GraphInterrupt as interrupt_ex:
        # El grafo fue pausado deliberadamente por el nodo human_approval (HITL)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        interrupt_value = interrupt_ex.args[0] if interrupt_ex.args else {}
        if isinstance(interrupt_value, list) and interrupt_value:
            interrupt_value = (
                interrupt_value[0].value
                if hasattr(interrupt_value[0], "value")
                else interrupt_value[0]
            )

        logger.info(
            "Grafo pausado por interrupción HITL en thread '%s': %s",
            thread_id,
            interrupt_value,
        )

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

        agent_output = AgentOutput(
            execution_id=input_data.execution_id,
            thread_id=thread_id,
            status=ExecutionStatus.WAITING_APPROVAL,
            response=str(message),
            data=interrupt_value
            if isinstance(interrupt_value, dict)
            else {"details": str(interrupt_value)},
            execution_time_ms=elapsed_ms,
            requires_approval=True,
            pending_approval_id=str(pending_id),
            metadata=input_data.metadata,
            completed_at=datetime.now(UTC),
        )

        try:
            async with async_session_factory() as db:
                await _persist_or_update_execution(
                    db,
                    input_data=input_data,
                    status_val=ExecutionStatus.WAITING_APPROVAL.value,
                    response_text=agent_output.response,
                    data_payload=agent_output.data,
                    execution_time_ms=agent_output.execution_time_ms,
                    requires_approval=True,
                    pending_approval_id=agent_output.pending_approval_id,
                )
        except Exception as db_err:
            logger.warning("Fallo al actualizar DB tras HITL pause: %s", db_err)

        return agent_output

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        logger.exception("Error no controlado durante la ejecución del grafo: %s", exc)
        agent_output = AgentOutput(
            execution_id=input_data.execution_id,
            thread_id=thread_id,
            status=ExecutionStatus.FAILED,
            response=f"Error durante la ejecución del agente: {exc}",
            execution_time_ms=elapsed_ms,
            error=str(exc),
            requires_approval=False,
            metadata=input_data.metadata,
            completed_at=datetime.now(UTC),
        )

        try:
            async with async_session_factory() as db:
                await _persist_or_update_execution(
                    db,
                    input_data=input_data,
                    status_val=ExecutionStatus.FAILED.value,
                    response_text=agent_output.response,
                    execution_time_ms=agent_output.execution_time_ms,
                    error_msg=str(exc),
                    completed_at=datetime.now(UTC),
                )
        except Exception:
            pass

        return agent_output


async def run_in_background(
    graph: Any,
    input_data: AgentInput,
) -> None:
    """Función de soporte para ejecución asíncrona delegada en BackgroundTasks."""
    try:
        await execute_graph_pipeline(graph, input_data)
    except Exception as exc:
        logger.error(
            "Fallo en ejecución en segundo plano '%s': %s",
            input_data.execution_id,
            exc,
        )


@router.post(
    "/trigger",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Disparar o continuar la ejecución del grafo cognitivo",
    description=(
        "Recibe un payload formal AgentInput, inicia o reanuda la ejecución del grafo LangGraph "
        "y devuelve AgentOutput con el resultado final o el estado de espera (HITL). "
        "Permite ejecución síncrona (200 OK) o asíncrona (202 Accepted)."
    ),
    responses={
        200: {
            "description": "Ejecución completada con éxito o pausada en espera de aprobación humana (HITL)."
        },
        202: {"description": "Ejecución encolada en segundo plano de forma asíncrona."},
        422: {"description": "Payload de entrada AgentInput no válido."},
    },
)
async def trigger_execution(
    input_data: AgentInput,
    request: Request,
    background_tasks: BackgroundTasks,
    sync: bool = Query(
        default=True,
        description="Si es False, inicia la ejecución en segundo plano y responde HTTP 202 Accepted.",
    ),
    graph: Any = Depends(get_agent_graph),
    db: AsyncSession = Depends(get_async_session),
) -> Any:
    """Punto de entrada principal para la ejecución de agentes en jg_agente."""
    # 1. Registrar o asegurar registro inicial en DB
    await _persist_or_update_execution(
        db,
        input_data=input_data,
        status_val=ExecutionStatus.IN_PROGRESS.value,
    )

    # 2. Flujo Asíncrono (sync=False o indicado en parámetros)
    async_requested = (
        not sync
        or bool(input_data.parameters.get("async"))
        or bool(input_data.parameters.get("background"))
    )

    if async_requested:
        background_tasks.add_task(run_in_background, graph, input_data)
        from fastapi.responses import JSONResponse

        accepted_output = AgentOutput(
            execution_id=input_data.execution_id,
            thread_id=input_data.thread_id,
            status=ExecutionStatus.IN_PROGRESS,
            response="Ejecución aceptada y encolada en segundo plano.",
            metadata=input_data.metadata,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=accepted_output.model_dump(mode="json"),
        )

    # 4. Flujo Síncrono (por defecto)
    output = await execute_graph_pipeline(graph, input_data)
    return output
