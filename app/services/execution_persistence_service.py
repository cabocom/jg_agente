# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de persistencia relacional y respaldo en disco para ejecuciones cognitivas."""

import asyncio
import contextlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.exceptions import PersistenceError
from app.db.models import CoreExecution
from app.db.session import async_session_factory
from app.models.io import (
    AgentInput,
    AgentOutput,
    PersistenceMetadata,
    PersistenceStatus,
)

logger = logging.getLogger("jg_agente.services.persistence")


def spool_emergency_execution(
    execution_id: str,
    payload: dict[str, Any],
) -> Path | None:
    """Almacena el estado/salida de la ejecución en disco ante caída de PostgreSQL."""
    try:
        spool_dir = Path(settings.EMERGENCY_PERSISTENCE_DIR)
        spool_dir.mkdir(parents=True, exist_ok=True)
        target_file = spool_dir / f"{execution_id}.json"
        target_file.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.warning(
            "Respaldo de emergencia escrito en '%s' para ejecución '%s'",
            target_file,
            execution_id,
        )
        return target_file
    except Exception as spool_err:
        logger.critical(
            "Fallo crítico: No se pudo escribir respaldo en disco para '%s': %s",
            execution_id,
            spool_err,
            exc_info=True,
        )
        return None


def _serialize_safe_json(data: Any) -> Any:
    """Serializa estructuras de datos complejas a JSON seguro o None."""
    if data is None:
        return None
    return json.loads(json.dumps(data, default=str))


def _extract_user_context(input_data: AgentInput) -> dict[str, Any] | None:
    """Extrae el diccionario de contexto de usuario de AgentInput."""
    ctx = input_data.user_context
    if ctx and hasattr(ctx, "model_dump"):
        return ctx.model_dump()
    return ctx if isinstance(ctx, dict) else None


def _update_existing_record(
    record: CoreExecution,
    status_val: str,
    response_text: str | None,
    safe_data: Any,
    execution_time_ms: float,
    requires_approval: bool,
    pending_approval_id: str | None,
    error_msg: str | None,
    completed_at: datetime | None,
) -> None:
    """Actualiza los campos modificados en un registro existente de CoreExecution."""
    record.status = status_val
    if response_text is not None:
        record.response = response_text
    if safe_data is not None:
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


async def persist_or_update_execution(
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
    """Crea o actualiza el registro de la ejecución en la tabla core_executions."""
    try:
        query = select(CoreExecution).where(CoreExecution.execution_id == input_data.execution_id)
        result = await db.execute(query)
        record = result.scalars().first()

        safe_data = _serialize_safe_json(data_payload)
        safe_params = _serialize_safe_json(input_data.parameters)
        safe_meta = _serialize_safe_json(input_data.metadata)
        user_ctx_dict = _extract_user_context(input_data)

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
            _update_existing_record(
                record,
                status_val,
                response_text,
                safe_data,
                execution_time_ms,
                requires_approval,
                pending_approval_id,
                error_msg,
                completed_at,
            )

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


async def persist_with_retry(
    input_data: AgentInput,
    status_val: str = "in_progress",
    response_text: str | None = None,
    data_payload: dict[str, Any] | None = None,
    execution_time_ms: float = 0.0,
    requires_approval: bool = False,
    pending_approval_id: str | None = None,
    error_msg: str | None = None,
    completed_at: datetime | None = None,
    max_retries: int | None = None,
    backoff_base: float | None = None,
) -> CoreExecution:
    """Persiste o actualiza la ejecución en core_executions con reintentos exponenciales."""
    retries = max_retries if max_retries is not None else settings.PERSISTENCE_MAX_RETRIES
    backoff = (
        backoff_base if backoff_base is not None else settings.PERSISTENCE_RETRY_BACKOFF_SECONDS
    )
    last_err: Exception | None = None

    for attempt in range(retries):
        try:
            async with async_session_factory() as db:
                return await persist_or_update_execution(
                    db,
                    input_data=input_data,
                    status_val=status_val,
                    response_text=response_text,
                    data_payload=data_payload,
                    execution_time_ms=execution_time_ms,
                    requires_approval=requires_approval,
                    pending_approval_id=pending_approval_id,
                    error_msg=error_msg,
                    completed_at=completed_at,
                )
        except Exception as exc:
            last_err = exc
            if attempt < retries - 1:
                wait_time = backoff * (2**attempt)
                logger.warning(
                    "Fallo transitorio al persistir '%s' en intento %d/%d: %s. Reintento en %.2fs...",
                    input_data.execution_id,
                    attempt + 1,
                    retries,
                    exc,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "Agotados los %d intentos de persistencia para '%s'. Fallo fatal: %s",
                    retries,
                    input_data.execution_id,
                    exc,
                    exc_info=True,
                )

    raise PersistenceError(
        f"Fallo irrecuperable tras {retries} reintentos al persistir ejecución '{input_data.execution_id}': {last_err}",
        original_error=last_err,
    )


async def persist_execution_outcome(
    input_data: AgentInput,
    agent_output: AgentOutput,
    status_val: str,
    error_msg: str | None = None,
    failure_detail: str | None = None,
) -> None:
    """Persiste el resultado de la ejecución con respaldo ante fallos de BD (Spool de emergencia)."""
    try:
        await persist_with_retry(
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
        spool_emergency_execution(input_data.execution_id, agent_output.model_dump(mode="json"))
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


__all__ = [
    "persist_execution_outcome",
    "persist_or_update_execution",
    "persist_with_retry",
    "spool_emergency_execution",
]
