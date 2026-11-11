# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de orquestación, ensamblado de grafo y ejecución de pipelines cognitivos."""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphInterrupt

from app.core.checkpointer import get_checkpointer
from app.core.correlation import get_correlation_id
from app.core.graph import GraphBuilder
from app.core.llm import get_chat_model
from app.core.registry import CapabilityRegistry
from app.db.exceptions import PersistenceError
from app.models.io import (
    AgentInput,
    AgentOutput,
    ExecutionStatus,
    PersistenceMetadata,
    PersistenceStatus,
)
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    resolve_caller_permissions,
)
from app.security.guard import SecurityGuard
from app.services.hitl_interrupt_service import handle_hitl_interrupt

logger = logging.getLogger("jg_agente.services.orchestrator")

GENERIC_EXECUTION_ERROR_MSG = (
    "Error interno durante la ejecución del agente (ID de incidencia: {execution_id}). "
    "Por favor, consulte los registros del sistema."
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


def _init_agent_state(input_data: AgentInput, cid: str | None, graph: Any) -> AgentState:
    """Inicializa la estructura de estado para el pipeline de LangGraph."""
    return {
        "request": input_data,
        "correlation_id": cid,
        "caller_permissions": resolve_caller_permissions({"request": input_data}),
        "messages": [HumanMessage(content=input_data.prompt)],
        "status": AgentExecutionStatus.OBSERVING,
        "current_step": 0,
        "retry_count": 0,
        "circuit_breaker_active": False,
        "checkpoint_degraded": bool(
            getattr(getattr(graph, "checkpointer", None), "is_degraded", False)
        ),
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


async def _persist_execution_outcome(
    input_data: AgentInput,
    agent_output: AgentOutput,
    status_val: str,
    error_msg: str | None = None,
    failure_detail: str | None = None,
) -> None:
    """Persiste el resultado de la ejecución con respaldo ante fallos de BD."""
    from app.api import executions as executions_api
    from app.services.execution_persistence_service import (
        persist_with_retry,
        spool_emergency_execution,
    )

    persist_fn = getattr(executions_api, "_persist_with_retry", persist_with_retry)
    spool_fn = getattr(executions_api, "_spool_emergency_execution", spool_emergency_execution)

    try:
        await persist_fn(
            input_data=input_data,
            status_val=status_val,
            response_text=agent_output.response,
            data_payload=agent_output.data,
            execution_time_ms=agent_output.execution_time_ms,
            requires_approval=agent_output.requires_approval,
            pending_approval_id=agent_output.pending_approval_id,
            error_msg=error_msg or agent_output.error,
            completed_at=agent_output.completed_at,
        )
        agent_output.metadata["persistence"] = PersistenceMetadata(
            status=PersistenceStatus.PERSISTED,
            persisted=True,
        ).model_dump()
    except (PersistenceError, Exception) as db_err:
        spool_fn(input_data.execution_id, agent_output.model_dump(mode="json"))
        logger.error(
            "Fallo irrecuperable al actualizar DB tras ejecución '%s': %s",
            input_data.execution_id,
            db_err,
            exc_info=True,
        )
        detail_msg = (
            failure_detail or f"Fallo crítico de persistencia para '{input_data.execution_id}'."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail_msg,
        ) from db_err


def _extract_final_output(
    final_state: dict[str, Any],
    input_data: AgentInput,
    thread_id: str,
    elapsed_ms: float,
) -> AgentOutput:
    """Extrae o normaliza el AgentOutput devuelto por LangGraph."""
    raw_output = final_state.get("output")
    if isinstance(raw_output, AgentOutput):
        return raw_output
    if isinstance(raw_output, dict):
        return AgentOutput(**raw_output)

    is_resolved = final_state.get("is_resolved", True)
    return AgentOutput(
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
    initial_state = _init_agent_state(input_data, cid, graph)

    try:
        final_state = await graph.ainvoke(initial_state, config=config)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        if isinstance(final_state, dict) and "__interrupt__" in final_state:
            items = final_state["__interrupt__"]
            val = (
                items[0].value
                if items and hasattr(items[0], "value")
                else (items[0] if items else {})
            )
            return await handle_hitl_interrupt(
                graph,
                config,
                input_data,
                thread_id,
                elapsed_ms,
                val,
                failure_detail=f"Fallo crítico de persistencia en pausa HITL para '{input_data.execution_id}'.",
            )

        agent_output = _extract_final_output(final_state, input_data, thread_id, elapsed_ms)
        await _persist_execution_outcome(
            input_data,
            agent_output,
            agent_output.status.value,
            failure_detail=f"Fallo crítico de persistencia tras finalización para '{input_data.execution_id}'.",
        )
        if cid:
            agent_output.correlation_id = cid
            if "correlation_id" not in agent_output.metadata:
                agent_output.metadata["correlation_id"] = cid
        return agent_output

    except GraphInterrupt as interrupt_ex:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        val = interrupt_ex.args[0] if interrupt_ex.args else {}
        if isinstance(val, list) and val:
            val = val[0].value if hasattr(val[0], "value") else val[0]
        return await handle_hitl_interrupt(
            graph,
            config,
            input_data,
            thread_id,
            elapsed_ms,
            val,
            failure_detail=f"Fallo crítico de persistencia en interrupción HITL para '{input_data.execution_id}'.",
        )

    except HTTPException:
        raise
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
        await _persist_execution_outcome(
            input_data,
            agent_output,
            ExecutionStatus.FAILED.value,
            error_msg=str(exc),
            failure_detail=f"Fallo crítico de persistencia al registrar fallo no controlado en '{input_data.execution_id}'.",
        )
        if cid:
            agent_output.correlation_id = cid
            if "correlation_id" not in agent_output.metadata:
                agent_output.metadata["correlation_id"] = cid
        return agent_output
