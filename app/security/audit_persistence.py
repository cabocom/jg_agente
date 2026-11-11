# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Persistencia asíncrona no bloqueante de registros de auditoría en PostgreSQL."""

import asyncio
import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CoreAuditRecord
from app.models.state import AuditRecord

logger = logging.getLogger("jg_agente.security.audit_persistence")


async def persist_audit_record_to_db(
    session_factory: async_sessionmaker[AsyncSession],
    audit_record: AuditRecord,
    execution_id: str | None = None,
) -> None:
    """Escribe un registro de auditoría en la tabla core_audit_records de forma tolerante a fallos."""
    try:
        async with session_factory() as session:
            db_record = CoreAuditRecord(
                execution_id=execution_id,
                event_type=audit_record.event_type,
                actor=audit_record.actor,
                details=audit_record.details,
                timestamp=audit_record.timestamp,
            )
            session.add(db_record)
            try:
                await session.commit()
            except IntegrityError as integ_err:
                await session.rollback()
                err_str = str(integ_err).lower()
                if execution_id and ("foreign key" in err_str or "violates foreign key" in err_str):
                    logger.warning(
                        "execution_id '%s' no encontrado en core_executions. Persistiendo evento '%s' desacoplado.",
                        execution_id,
                        audit_record.event_type,
                    )
                    details_copy = dict(audit_record.details)
                    details_copy["unlinked_execution_id"] = execution_id
                    fallback = CoreAuditRecord(
                        execution_id=None,
                        event_type=audit_record.event_type,
                        actor=audit_record.actor,
                        details=details_copy,
                        timestamp=audit_record.timestamp,
                    )
                    session.add(fallback)
                    await session.commit()
                else:
                    raise
    except Exception as exc:
        logger.error(
            "Fallo persistiendo registro de auditoría '%s' en PostgreSQL: %s",
            audit_record.event_type,
            exc,
        )


def schedule_audit_persistence(
    session_factory: async_sessionmaker[AsyncSession],
    pending_tasks: set[asyncio.Task[Any]],
    audit_record: AuditRecord,
    execution_id: str | None = None,
    auto_persist: bool = True,
) -> None:
    """Programa la persistencia asíncrona del registro en PostgreSQL en el bucle de eventos."""
    if not auto_persist:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug(
            "Sin event loop activo para persistir evento '%s' a BD. Almacenado en historial.",
            audit_record.event_type,
        )
        return

    task = loop.create_task(persist_audit_record_to_db(session_factory, audit_record, execution_id))
    pending_tasks.add(task)
    task.add_done_callback(pending_tasks.discard)
