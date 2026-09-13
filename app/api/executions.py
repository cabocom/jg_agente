"""Endpoints REST para el control y disparo de ejecuciones cognitivas en jg_agente."""

import contextlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphInterrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.checkpointer import get_checkpointer
from app.core.correlation import get_correlation_id
from app.core.graph import GraphBuilder
from app.core.llm import get_chat_model
from app.core.registry import CapabilityRegistry
from app.db.exceptions import PersistenceError
from app.db.models import CoreExecution
from app.db.session import async_session_factory, get_async_session
from app.models.io import (
    AgentInput,
    AgentOutput,
    ExecutionStatus,
    ExecutionThreadDetail,
    HITLResolutionRequest,
    PersistenceMetadata,
    PersistenceStatus,
)
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalStatus,
    resolve_caller_permissions,
)
from app.security.auth import verify_control_plane_auth
from app.security.guard import SecurityGuard

logger = logging.getLogger("jg_agente.api.executions")

GENERIC_EXECUTION_ERROR_MSG = (
    "Error interno durante la ejecución del agente (ID de incidencia: {execution_id}). "
    "Por favor, consulte los registros del sistema."
)

router = APIRouter(
    prefix="/executions",
    tags=["Executions"],
    dependencies=[Depends(verify_control_plane_auth)],
)


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
) -> CoreExecution:
    """Crea o actualiza el registro de la ejecución en la tabla core_executions de forma transaccional."""
    try:
        query = select(CoreExecution).where(CoreExecution.execution_id == input_data.execution_id)
        result = await db.execute(query)
        record = result.scalars().first()

        user_ctx_dict = (
            input_data.user_context.model_dump()
            if input_data.user_context and hasattr(input_data.user_context, "model_dump")
            else (input_data.user_context if isinstance(input_data.user_context, dict) else None)
        )

        safe_data = (
            json.loads(json.dumps(data_payload, default=str)) if data_payload is not None else None
        )
        safe_params = (
            json.loads(json.dumps(input_data.parameters, default=str))
            if input_data.parameters is not None
            else None
        )
        safe_meta = (
            json.loads(json.dumps(input_data.metadata, default=str))
            if input_data.metadata is not None
            else None
        )

        if record is None:
            record = CoreExecution(
                execution_id=input_data.execution_id,
                thread_id=input_data.thread_id,
                status=status_val,
                prompt=input_data.prompt,
                response=response_text,
                parameters=safe_params,
                data=safe_data,
                user_context=user_ctx_dict,
                execution_time_ms=execution_time_ms,
                requires_approval=requires_approval,
                pending_approval_id=pending_approval_id,
                error=error_msg,
                metadata_=safe_meta,
                created_at=input_data.created_at,
                completed_at=completed_at,
            )
            db.add(record)
        else:
            record.status = status_val
            if response_text is not None:
                record.response = response_text
            if data_payload is not None:
                record.data = safe_data
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
        logger.error(
            "Fallo crítico al persistir ejecución '%s' en core_executions: %s",
            input_data.execution_id,
            exc,
            exc_info=True,
        )
        raise PersistenceError(
            f"Fallo en persistencia de ejecución {input_data.execution_id}: {exc}",
            original_error=exc,
        ) from exc


async def execute_graph_pipeline(
    graph: Any,
    input_data: AgentInput,
) -> AgentOutput:
    """Ejecuta el ciclo del grafo LangGraph con captura de pausas HITL y finalización."""
    start_time = time.perf_counter()
    thread_id = input_data.thread_id
    cid = (
        input_data.correlation_id
        or (
            input_data.metadata.get("correlation_id")
            if isinstance(input_data.metadata, dict)
            else None
        )
        or get_correlation_id()
    )
    config = {"configurable": {"thread_id": thread_id, "correlation_id": cid}}

    initial_state: AgentState = {
        "request": input_data,
        "correlation_id": cid,
        "caller_permissions": resolve_caller_permissions({"request": input_data}),
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
        "cognitive_steps": [],
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

            # Recuperar saltos cognitivos previos acumulados en el checkpoint
            snapshot_steps: list[dict[str, Any]] = []
            try:
                state_snapshot = await graph.aget_state(config)
                if state_snapshot and state_snapshot.values:
                    existing_cog_steps = state_snapshot.values.get("cognitive_steps") or []
                    for step_item in existing_cog_steps:
                        if hasattr(step_item, "model_dump"):
                            snapshot_steps.append(step_item.model_dump(mode="json"))
                        elif isinstance(step_item, dict):
                            snapshot_steps.append(step_item)
            except Exception as snap_err:
                logger.warning(
                    "No se pudo obtener snapshot de estado en interrupción HITL: %s", snap_err
                )

            # Salto cognitivo para el paso de human_approval en espera
            approval_step = {
                "step_id": f"cog_approval_{int(time.time() * 1000)}",
                "node": "human_approval",
                "title": "Control de Aprobación Humana (HITL)",
                "action": "Pausa de Seguridad Operacional",
                "description": (
                    "Operación de alto riesgo detenida. Requiere autorización humana explícita "
                    "desde el panel de control para continuar."
                ),
                "status": "waiting_approval",
                "details": interrupt_value if isinstance(interrupt_value, dict) else {},
                "duration_ms": 0.0,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            snapshot_steps.append(approval_step)

            data_payload = (
                dict(interrupt_value)
                if isinstance(interrupt_value, dict)
                else {"details": str(interrupt_value)}
            )
            data_payload["cognitive_steps"] = snapshot_steps
            data_payload["steps"] = snapshot_steps

            agent_output = AgentOutput(
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
                agent_output.metadata["persistence"] = PersistenceMetadata(
                    status=PersistenceStatus.PERSISTED,
                    persisted=True,
                ).model_dump()
            except (PersistenceError, Exception) as db_err:
                logger.error(
                    "Fallo al actualizar DB tras HITL pause en '%s': %s",
                    input_data.execution_id,
                    db_err,
                    exc_info=True,
                )
                agent_output.metadata["persistence"] = PersistenceMetadata(
                    status=PersistenceStatus.DEGRADED,
                    persisted=False,
                    error=str(db_err),
                    error_type=type(db_err).__name__,
                ).model_dump()

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
            agent_output.metadata["persistence"] = PersistenceMetadata(
                status=PersistenceStatus.PERSISTED,
                persisted=True,
            ).model_dump()
        except (PersistenceError, Exception) as db_err:
            logger.error(
                "Fallo al actualizar DB tras finalización en '%s': %s",
                input_data.execution_id,
                db_err,
                exc_info=True,
            )
            agent_output.metadata["persistence"] = PersistenceMetadata(
                status=PersistenceStatus.DEGRADED,
                persisted=False,
                error=str(db_err),
                error_type=type(db_err).__name__,
            ).model_dump()

        if cid:
            agent_output.correlation_id = cid
            if "correlation_id" not in agent_output.metadata:
                agent_output.metadata["correlation_id"] = cid

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
            agent_output.metadata["persistence"] = PersistenceMetadata(
                status=PersistenceStatus.PERSISTED,
                persisted=True,
            ).model_dump()
        except (PersistenceError, Exception) as db_err:
            logger.error(
                "Fallo al actualizar DB tras HITL pause en '%s': %s",
                input_data.execution_id,
                db_err,
                exc_info=True,
            )
            agent_output.metadata["persistence"] = PersistenceMetadata(
                status=PersistenceStatus.DEGRADED,
                persisted=False,
                error=str(db_err),
                error_type=type(db_err).__name__,
            ).model_dump()

        if cid:
            agent_output.correlation_id = cid
            if "correlation_id" not in agent_output.metadata:
                agent_output.metadata["correlation_id"] = cid

        return agent_output

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        logger.exception("Error no controlado durante la ejecución del grafo: %s", exc)
        agent_output = AgentOutput(
            execution_id=input_data.execution_id,
            thread_id=thread_id,
            status=ExecutionStatus.FAILED,
            response=GENERIC_EXECUTION_ERROR_MSG.format(execution_id=input_data.execution_id),
            execution_time_ms=elapsed_ms,
            error=f"InternalExecutionError: Incidencia registrada con ID {input_data.execution_id}",
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
            agent_output.metadata["persistence"] = PersistenceMetadata(
                status=PersistenceStatus.PERSISTED,
                persisted=True,
            ).model_dump()
        except (PersistenceError, Exception) as db_err:
            logger.error(
                "Degradación de persistencia al registrar fallo no controlado en '%s': %s",
                input_data.execution_id,
                db_err,
                exc_info=True,
            )
            agent_output.metadata["persistence"] = PersistenceMetadata(
                status=PersistenceStatus.DEGRADED,
                persisted=False,
                error=str(db_err),
                error_type=type(db_err).__name__,
            ).model_dump()

        if cid:
            agent_output.correlation_id = cid
            if "correlation_id" not in agent_output.metadata:
                agent_output.metadata["correlation_id"] = cid

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
    # 0. Sincronizar e inyectar correlation_id
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

    # 1. Registrar o asegurar registro inicial en DB
    initial_persistence: PersistenceMetadata
    try:
        await _persist_or_update_execution(
            db,
            input_data=input_data,
            status_val=ExecutionStatus.IN_PROGRESS.value,
        )
        initial_persistence = PersistenceMetadata(
            status=PersistenceStatus.PERSISTED,
            persisted=True,
        )
    except (PersistenceError, Exception) as p_err:
        logger.error(
            "Degradación de persistencia al registrar inicio de ejecución '%s': %s",
            input_data.execution_id,
            p_err,
            exc_info=True,
        )
        initial_persistence = PersistenceMetadata(
            status=PersistenceStatus.DEGRADED,
            persisted=False,
            error=str(p_err),
            error_type=type(p_err).__name__,
        )
    input_data.metadata["persistence"] = initial_persistence.model_dump()

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
            correlation_id=cid,
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


@router.get(
    "/{thread_id}",
    response_model=ExecutionThreadDetail,
    status_code=status.HTTP_200_OK,
    summary="Consultar estado de una ejecución por thread_id",
    description=(
        "Recupera el estado operacional actual, historial de pasos ejecutados, evaluación de riesgos, "
        "interrupciones HITL y errores acumulados del hilo de ejecución a partir del checkpointer y base de datos."
    ),
    responses={
        200: {"description": "Detalle del hilo de ejecución recuperado con éxito."},
        404: {"description": "Hilo de ejecución no encontrado."},
    },
)
async def get_execution_by_thread_id(
    thread_id: str,
    graph: Any = Depends(get_agent_graph),
    db: AsyncSession = Depends(get_async_session),
) -> ExecutionThreadDetail:
    """Consulta el estado, historial y checkpoints de una sesión o hilo de ejecución."""
    # 1. Consultar estado en el checkpointer del grafo LangGraph
    state_snapshot: Any = None
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state_snapshot = await graph.aget_state(config)
    except Exception as exc:
        logger.warning(
            "No se pudo consultar el estado en el checkpointer para thread '%s': %s",
            thread_id,
            exc,
        )

    # 2. Consultar persistencia relacional en core_executions
    db_record: CoreExecution | None = None
    try:
        query = (
            select(CoreExecution)
            .where(CoreExecution.thread_id == thread_id)
            .order_by(CoreExecution.created_at.desc())
        )
        res = await db.execute(query)
        db_record = res.scalars().first()
    except Exception as db_err:
        logger.warning(
            "No se pudo consultar el registro en core_executions para thread '%s': %s",
            thread_id,
            db_err,
        )

    # 3. Si no existe en checkpointer ni en base de datos, responder 404
    has_checkpoint = state_snapshot is not None and bool(getattr(state_snapshot, "values", None))
    if not has_checkpoint and db_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hilo de ejecución '{thread_id}' no encontrado.",
        )

    vals: dict[str, Any] = state_snapshot.values if has_checkpoint else {}

    # 4. Extraer y armonizar campos desde el snapshot y la BD
    request_obj = vals.get("request")
    output_obj = vals.get("output")

    # Identificadores
    execution_id: str | None = None
    if request_obj and hasattr(request_obj, "execution_id"):
        execution_id = str(request_obj.execution_id)
    elif isinstance(request_obj, dict) and request_obj.get("execution_id"):
        execution_id = str(request_obj["execution_id"])
    elif db_record:
        execution_id = db_record.execution_id

    # Prompt
    prompt: str | None = None
    if request_obj and hasattr(request_obj, "prompt"):
        prompt = str(request_obj.prompt)
    elif isinstance(request_obj, dict) and request_obj.get("prompt"):
        prompt = str(request_obj["prompt"])
    elif db_record:
        prompt = db_record.prompt

    # Respuesta
    response_text: str | None = None
    if output_obj and hasattr(output_obj, "response"):
        response_text = str(output_obj.response)
    elif isinstance(output_obj, dict) and output_obj.get("response"):
        response_text = str(output_obj["response"])
    elif db_record:
        response_text = db_record.response

    # Nodos siguientes en LangGraph
    next_nodes: list[str] = (
        list(state_snapshot.next)
        if state_snapshot and getattr(state_snapshot, "next", None)
        else []
    )

    # Estado
    raw_status = vals.get("status")
    if next_nodes and ("human_approval" in next_nodes or "risk_assess" in next_nodes):
        status_val: str = ExecutionStatus.WAITING_APPROVAL.value
    elif raw_status:
        status_val = raw_status.value if hasattr(raw_status, "value") else str(raw_status)
        # Mapear estados operacionales a ExecutionStatus si es necesario
        if status_val == AgentExecutionStatus.RESOLVED.value:
            status_val = ExecutionStatus.COMPLETED.value
        elif status_val == AgentExecutionStatus.AWAITING_APPROVAL.value:
            status_val = ExecutionStatus.WAITING_APPROVAL.value
    elif db_record:
        status_val = db_record.status
    else:
        status_val = ExecutionStatus.IN_PROGRESS.value

    # Plan
    plan_obj = vals.get("plan")
    plan_dict: dict[str, Any] | None = None
    if plan_obj is not None:
        if hasattr(plan_obj, "model_dump"):
            plan_dict = plan_obj.model_dump(mode="json")
        elif isinstance(plan_obj, dict):
            plan_dict = plan_obj

    # Pasos y saltos cognitivos
    raw_cog_steps = (
        vals.get("cognitive_steps")
        or (
            db_record.data.get("cognitive_steps")
            if (db_record and isinstance(db_record.data, dict))
            else None
        )
        or []
    )
    cog_steps_list: list[dict[str, Any]] = []
    for rec in raw_cog_steps:
        if hasattr(rec, "model_dump"):
            cog_steps_list.append(rec.model_dump(mode="json"))
        elif isinstance(rec, dict):
            cog_steps_list.append(rec)
        else:
            cog_steps_list.append({"raw": str(rec)})

    raw_exec_records = (
        vals.get("execution_records")
        or (
            db_record.data.get("execution_records")
            if (db_record and isinstance(db_record.data, dict))
            else None
        )
        or []
    )
    exec_steps_list: list[dict[str, Any]] = []
    for rec in raw_exec_records:
        if hasattr(rec, "model_dump"):
            exec_steps_list.append(rec.model_dump(mode="json"))
        elif isinstance(rec, dict):
            exec_steps_list.append(rec)
        else:
            exec_steps_list.append({"raw": str(rec)})

    # steps_list unificado: prioriza la traza cognitiva completa
    steps_list = cog_steps_list if cog_steps_list else exec_steps_list

    # Gobernanza HITL
    appr_obj = vals.get("approval")
    approval_status_val: str | None = None
    if appr_obj is not None:
        if hasattr(appr_obj, "status"):
            approval_status_val = (
                appr_obj.status.value if hasattr(appr_obj.status, "value") else str(appr_obj.status)
            )
        elif isinstance(appr_obj, dict) and appr_obj.get("status"):
            approval_status_val = str(appr_obj["status"])
    elif status_val == ExecutionStatus.WAITING_APPROVAL.value:
        approval_status_val = ApprovalStatus.PENDING.value

    requires_approval: bool = bool(
        vals.get("requires_approval")
        or vals.get("human_intervention_required")
        or (next_nodes and "human_approval" in next_nodes)
        or (db_record and db_record.requires_approval)
    )

    pending_approval_id: str | None = (
        str(vals.get("pending_approval_id"))
        if vals.get("pending_approval_id")
        else (db_record.pending_approval_id if db_record else None)
    )
    if requires_approval and not pending_approval_id:
        pending_approval_id = "human_approval_required"

    # Errores
    raw_errors = vals.get("errors") or []
    errors_list: list[dict[str, Any]] = []
    for err in raw_errors:
        if hasattr(err, "model_dump"):
            errors_list.append(err.model_dump(mode="json"))
        elif isinstance(err, dict):
            errors_list.append(err)
        else:
            errors_list.append({"message": str(err)})
    if not errors_list and db_record and db_record.error:
        errors_list.append({"message": db_record.error, "code": "DB_RECORD_ERROR"})

    # Checkpoint ID
    checkpoint_id: str | None = None
    if state_snapshot and getattr(state_snapshot, "config", None):
        cfg = state_snapshot.config.get("configurable", {})
        checkpoint_id = cfg.get("checkpoint_id")

    # Metadatos
    metadata: dict[str, Any] = (
        dict(db_record.metadata_) if (db_record and db_record.metadata_) else {}
    )
    if request_obj and hasattr(request_obj, "metadata"):
        metadata.update(request_obj.metadata)
    elif isinstance(request_obj, dict) and "metadata" in request_obj:
        metadata.update(request_obj["metadata"])

    # Fechas
    created_at = db_record.created_at if db_record else None
    if created_at is None and request_obj and hasattr(request_obj, "created_at"):
        created_at = request_obj.created_at

    completed_at = db_record.completed_at if db_record else None
    if completed_at is None and output_obj and hasattr(output_obj, "completed_at"):
        completed_at = output_obj.completed_at

    req_cid = getattr(request_obj, "correlation_id", None) if request_obj is not None else None
    correlation_id: str | None = (
        vals.get("correlation_id")
        or req_cid
        or (metadata.get("correlation_id") if isinstance(metadata, dict) else None)
        or get_correlation_id()
    )

    return ExecutionThreadDetail(
        thread_id=thread_id,
        execution_id=execution_id,
        correlation_id=correlation_id,
        status=status_val,
        prompt=prompt,
        response=response_text,
        current_step=int(vals.get("current_step", len(steps_list))),
        next_nodes=next_nodes,
        plan=plan_dict,
        steps=steps_list,
        cognitive_steps=cog_steps_list,
        approval_status=approval_status_val,
        requires_approval=requires_approval,
        pending_approval_id=pending_approval_id,
        errors=errors_list,
        checkpoint_id=checkpoint_id,
        metadata=metadata,
        created_at=created_at,
        completed_at=completed_at,
    )


async def _resolve_hitl_execution(
    thread_id: str,
    approved: bool,
    payload: HITLResolutionRequest,
    graph: Any,
    db: AsyncSession,
) -> AgentOutput:
    """Reanuda o cancela una ejecución detenida en el nodo human_approval mediante Command(resume=...)."""
    # 1. Validar existencia del hilo en el checkpointer
    config = {"configurable": {"thread_id": thread_id}}
    state_snapshot: Any = None
    try:
        state_snapshot = await graph.aget_state(config)
    except Exception as exc:
        logger.warning("Error al consultar checkpointer para thread '%s': %s", thread_id, exc)

    if not state_snapshot or not getattr(state_snapshot, "values", None):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hilo de ejecución '{thread_id}' no encontrado en el checkpointer.",
        )

    # 2. Validar que el hilo se encuentre en espera de aprobación
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

    # 3. Construir el Command nativo de LangGraph con el payload de resume
    from langgraph.types import Command

    resume_payload: dict[str, Any] = {
        "approved": approved,
        "status": ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value,
        "approver": payload.approver,
        "notes": payload.notes
        or ("Aprobado por operador" if approved else "Rechazado por operador"),
        "action": "approve" if approved else "reject",
    }
    command: Command[Any] = Command(resume=resume_payload)

    # 4. Reanudar ejecución del grafo
    start_time = time.perf_counter()
    try:
        final_state = await graph.ainvoke(command, config=config)
    except GraphInterrupt:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return AgentOutput(
            execution_id=str(
                state_snapshot.values.get("request", {}).execution_id
                if hasattr(state_snapshot.values.get("request"), "execution_id")
                else "exec-hitl"
            ),
            thread_id=thread_id,
            status=ExecutionStatus.WAITING_APPROVAL,
            response="Pausa HITL subsiguiente activada.",
            execution_time_ms=elapsed_ms,
            requires_approval=True,
            pending_approval_id="human_approval_required",
            completed_at=datetime.now(UTC),
        )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    # 5. Formatear AgentOutput resultante
    raw_output = final_state.get("output")
    agent_output: AgentOutput
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
    cog_steps = final_state.get("cognitive_steps") or []
    formatted_steps = [
        s.model_dump(mode="json") if hasattr(s, "model_dump") else s for s in cog_steps
    ]
    agent_output.data["cognitive_steps"] = formatted_steps
    agent_output.data["steps"] = formatted_steps

    rejection_text = (
        payload.notes or getattr(payload, "justification", None) or getattr(payload, "reason", None)
    )
    if not approved:
        agent_output.status = ExecutionStatus.CANCELLED
        if rejection_text:
            agent_output.response = rejection_text
        elif not agent_output.response or agent_output.response.startswith("Ejecución finalizada"):
            agent_output.response = "Ejecución cancelada por rechazo de operador (HITL)."

    # 6. Actualizar persistencia en core_executions
    req_data = final_state.get("request")
    dummy_input = AgentInput(
        execution_id=agent_output.execution_id,
        thread_id=thread_id,
        prompt=getattr(req_data, "prompt", "HITL Decision") if req_data else "HITL Decision",
    )
    try:
        await _persist_or_update_execution(
            db,
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
        logger.error(
            "Degradación de persistencia al actualizar resolución HITL en '%s': %s",
            agent_output.execution_id,
            db_err,
            exc_info=True,
        )
        agent_output.metadata["persistence"] = PersistenceMetadata(
            status=PersistenceStatus.DEGRADED,
            persisted=False,
            error=str(db_err),
            error_type=type(db_err).__name__,
        ).model_dump()

    return agent_output


@router.post(
    "/{thread_id}/approve",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Aprobar ejecución pausada en HITL por thread_id",
    description="Reanuda la ejecución del grafo para el hilo indicado tras autorización humana.",
    responses={
        200: {"description": "Ejecución reanudada y finalizada con éxito."},
        400: {"description": "El hilo no se encuentra en estado de espera de aprobación."},
        404: {"description": "Hilo de ejecución no encontrado."},
        409: {"description": "El hilo ya ha finalizado previamente."},
    },
)
async def approve_execution_by_thread_id(
    thread_id: str,
    payload: HITLResolutionRequest | None = None,
    graph: Any = Depends(get_agent_graph),
    db: AsyncSession = Depends(get_async_session),
) -> AgentOutput:
    """Reanuda el grafo en el paso de ejecución con aprobación del operador."""
    req_payload = payload or HITLResolutionRequest()
    return await _resolve_hitl_execution(
        thread_id=thread_id,
        approved=True,
        payload=req_payload,
        graph=graph,
        db=db,
    )


@router.post(
    "/{thread_id}/reject",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Rechazar ejecución pausada en HITL por thread_id",
    description="Cancela la ejecución del grafo para el hilo indicado tras rechazo humano.",
    responses={
        200: {"description": "Ejecución cancelada con estado cancelled."},
        400: {"description": "El hilo no se encuentra en estado de espera de aprobación."},
        404: {"description": "Hilo de ejecución no encontrado."},
        409: {"description": "El hilo ya ha finalizado previamente."},
    },
)
async def reject_execution_by_thread_id(
    thread_id: str,
    payload: HITLResolutionRequest | None = None,
    graph: Any = Depends(get_agent_graph),
    db: AsyncSession = Depends(get_async_session),
) -> AgentOutput:
    """Cancela el plan y concluye el grafo con estado cancelled."""
    req_payload = payload or HITLResolutionRequest()
    return await _resolve_hitl_execution(
        thread_id=thread_id,
        approved=False,
        payload=req_payload,
        graph=graph,
        db=db,
    )


@router.post(
    "/approve",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Aprobar ejecución pausada en HITL (payload con thread_id)",
    description="Reanuda la ejecución del grafo tras autorización humana indicando thread_id en el cuerpo.",
    responses={
        200: {"description": "Ejecución reanudada y finalizada con éxito."},
        400: {"description": "El hilo no se encuentra en estado de espera de aprobación."},
        404: {"description": "Hilo de ejecución no encontrado."},
        409: {"description": "El hilo ya ha finalizado previamente."},
        422: {"description": "thread_id ausente en el payload."},
    },
)
async def approve_execution(
    payload: HITLResolutionRequest,
    graph: Any = Depends(get_agent_graph),
    db: AsyncSession = Depends(get_async_session),
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
        db=db,
    )


@router.post(
    "/reject",
    response_model=AgentOutput,
    status_code=status.HTTP_200_OK,
    summary="Rechazar ejecución pausada en HITL (payload con thread_id)",
    description="Cancela la ejecución del grafo tras rechazo humano indicando thread_id en el cuerpo.",
    responses={
        200: {"description": "Ejecución cancelada con estado cancelled."},
        400: {"description": "El hilo no se encuentra en estado de espera de aprobación."},
        404: {"description": "Hilo de ejecución no encontrado."},
        409: {"description": "El hilo ya ha finalizado previamente."},
        422: {"description": "thread_id ausente en el payload."},
    },
)
async def reject_execution(
    payload: HITLResolutionRequest,
    graph: Any = Depends(get_agent_graph),
    db: AsyncSession = Depends(get_async_session),
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
        db=db,
    )
