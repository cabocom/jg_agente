# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de auditoría de seguridad inmutable para jg_agente.

Registra en la tabla core_audit_records de PostgreSQL y en memoria cada evento,
delegando la formulación específica en AuditRecorder (SOLID/ISP).
"""

import asyncio
import logging
import threading
from collections import deque
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.correlation import get_correlation_id
from app.models.state import (
    AuditRecord,
    SecurityEvaluationResult,
)
from app.security.audit_persistence import (
    persist_audit_record_to_db,
    schedule_audit_persistence,
)
from app.security.audit_recorder import AuditRecorder

logger = logging.getLogger("jg_agente.security.audit")


class SecurityAuditLogger:
    """Registrador de auditoría de seguridad para el Core de jg_agente."""

    @staticmethod
    def _resolve_correlation_id(correlation_id: str | None = None) -> str | None:
        """Resuelve el correlation_id explícito o lo recupera del contexto asíncrono activo."""
        return correlation_id or get_correlation_id()

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        auto_persist: bool = True,
        max_history: int | None = None,
    ) -> None:
        capacity = (
            max_history
            if max_history is not None
            else getattr(settings, "AUDIT_LOG_MAX_HISTORY", 1000)
        )
        self._history: deque[AuditRecord] = deque(maxlen=capacity)
        if session_factory is None:
            from app.db.session import async_session_factory

            self._session_factory = async_session_factory
        else:
            self._session_factory = session_factory
        self._auto_persist = auto_persist
        self._pending_tasks: set[asyncio.Task[Any]] = set()

        self._recorder = AuditRecorder(
            history=self._history,
            schedule_persistence=self._schedule_persistence,
            resolve_correlation_id=self._resolve_correlation_id,
        )

    def _schedule_persistence(
        self,
        audit_record: AuditRecord,
        execution_id: str | None = None,
    ) -> None:
        """Programa la persistencia asíncrona del registro en PostgreSQL en segundo plano."""
        schedule_audit_persistence(
            self._session_factory,
            self._pending_tasks,
            audit_record,
            execution_id,
            self._auto_persist,
        )

    async def _persist_to_db(
        self,
        audit_record: AuditRecord,
        execution_id: str | None = None,
    ) -> None:
        """Escribe un registro de auditoría en la tabla core_audit_records."""
        await persist_audit_record_to_db(self._session_factory, audit_record, execution_id)

    @property
    def recorder(self) -> AuditRecorder:
        """Ingestor especializado en la recepción y formulación de eventos de auditoría."""
        return self._recorder

    @property
    def history(self) -> list[AuditRecord]:
        """Copia inmutable del historial de auditoría en memoria."""
        return list(self._history)

    @property
    def max_history(self) -> int | None:
        """Capacidad máxima configurada para el búfer circular en memoria."""
        return self._history.maxlen

    def record(
        self,
        evaluation: SecurityEvaluationResult,
        execution_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra el resultado formal de una evaluación de seguridad."""
        return self._recorder.record(evaluation, execution_id, correlation_id)

    def get_history(self) -> list[AuditRecord]:
        """Retorna una copia inmutable del historial de auditoría en memoria."""
        return list(self._history)

    def clear(self) -> None:
        """Limpia el buffer de auditoría en memoria."""
        self._history.clear()

    async def flush(self, timeout: float = 5.0) -> None:
        """Espera a que finalicen todas las tareas de persistencia asíncrona pendientes."""
        if not self._pending_tasks:
            return
        pending = list(self._pending_tasks)
        if pending:
            await asyncio.wait(pending, timeout=timeout)

    async def close(self) -> None:
        """Cierra el registrador asegurando el vaciado de tareas en segundo plano."""
        await self.flush()

    def __getattr__(self, name: str) -> Any:
        """Delegación transparente a AuditRecorder para métodos de registro especializados."""
        if hasattr(self._recorder, name):
            return getattr(self._recorder, name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")


_default_audit_logger: SecurityAuditLogger | None = None
_audit_logger_lock = threading.Lock()


def get_security_audit_logger() -> SecurityAuditLogger:
    """Factory singleton thread-safe para obtener SecurityAuditLogger."""
    global _default_audit_logger
    if _default_audit_logger is None:
        with _audit_logger_lock:
            if _default_audit_logger is None:
                _default_audit_logger = SecurityAuditLogger()
    return _default_audit_logger


get_audit_logger = get_security_audit_logger


__all__ = [
    "AuditRecorder",
    "SecurityAuditLogger",
    "get_audit_logger",
    "get_security_audit_logger",
]
