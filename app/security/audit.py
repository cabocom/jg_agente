# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de auditoría de seguridad inmutable para jg_agente.

Registra en la tabla core_audit_records de PostgreSQL y en memoria cada estímulo,
decisión de riesgo, ejecución de herramienta y cambio de estado, garantizando
persistencia no bloqueante para el ciclo asíncrono del agente.
"""

import asyncio
import logging
import threading
from collections import deque
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.correlation import get_correlation_id
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    ApprovalRecord,
    AuditRecord,
    PolicyDecision,
    SecurityEvaluationResult,
)
from app.models.tools import RiskLevel, ToolResult
from app.security.audit_builders import (
    build_approval_record,
    build_custom_event_record,
    build_security_decision_record,
    build_state_transition_record,
    build_stimulus_record,
    build_tool_execution_record,
)
from app.security.audit_persistence import (
    persist_audit_record_to_db,
    schedule_audit_persistence,
)

logger = logging.getLogger("jg_agente.security.audit")


class SecurityAuditLogger:
    """Registrador de auditoría de seguridad para el Core de jg_agente.

    Mantiene una traza inmutable en memoria y persiste de forma asíncrona no bloqueante
    en la tabla core_audit_records de la base de datos PostgreSQL.
    """

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

    def record(
        self,
        evaluation: SecurityEvaluationResult,
        execution_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra el resultado formal de una evaluación de seguridad (SecurityGuard)."""
        log_msg = (
            f"[SecurityGuard] Decisión={evaluation.decision.value} | Operación={evaluation.operation} "
            f"| Target='{evaluation.target_resource}' | Riesgo={evaluation.risk_level.value} "
            f"| Motivo='{evaluation.reason}'"
        )
        if evaluation.decision == PolicyDecision.DENY:
            logger.error(log_msg)
        elif evaluation.decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        cid = self._resolve_correlation_id(correlation_id)
        record = build_security_decision_record(evaluation, execution_id, cid)
        self._history.append(record)
        self._schedule_persistence(record, execution_id)
        return record

    def record_stimulus(
        self,
        input_data: AgentInput,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra la recepción de un nuevo estímulo de entrada (AgentInput)."""
        cid = self._resolve_correlation_id(
            correlation_id or input_data.correlation_id or input_data.metadata.get("correlation_id")
        )
        record = build_stimulus_record(input_data, cid)
        self._history.append(record)
        self._schedule_persistence(record, input_data.execution_id)
        return record

    def record_tool_execution(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: ToolResult,
        risk_level: RiskLevel = RiskLevel.LOW,
        execution_id: str | None = None,
        thread_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra la ejecución física o mock de una herramienta (AgentTool)."""
        cid = self._resolve_correlation_id(correlation_id)
        record = build_tool_execution_record(
            tool_name, tool_args, result, risk_level, execution_id, thread_id, cid
        )
        self._history.append(record)
        self._schedule_persistence(record, execution_id)
        return record

    def record_state_transition(
        self,
        old_status: AgentExecutionStatus | str,
        new_status: AgentExecutionStatus | str,
        execution_id: str | None = None,
        thread_id: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra una transición de estado en el ciclo operacional del agente."""
        cid = self._resolve_correlation_id(correlation_id)
        record = build_state_transition_record(
            old_status, new_status, execution_id, thread_id, reason, cid
        )
        self._history.append(record)
        self._schedule_persistence(record, execution_id)
        return record

    def record_approval(
        self,
        approval: ApprovalRecord,
        execution_id: str | None = None,
        thread_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra la solicitud o resolución de una aprobación humana (HITL)."""
        cid = self._resolve_correlation_id(correlation_id)
        record = build_approval_record(approval, execution_id, thread_id, cid)
        self._history.append(record)
        self._schedule_persistence(record, execution_id)
        return record

    def record_event(
        self,
        event_type: str,
        details: dict[str, Any],
        actor: str = "agent",
        execution_id: str | None = None,
        risk_level: RiskLevel | str | None = None,
        result: Any = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra un evento estructurado genérico en auditoría."""
        cid = self._resolve_correlation_id(correlation_id or details.get("correlation_id"))
        record = build_custom_event_record(
            event_type, details, actor, execution_id, risk_level, result, cid
        )
        self._history.append(record)
        self._schedule_persistence(record, execution_id)
        return record

    def record_audit_record(
        self,
        record: AuditRecord,
        execution_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Ingesta un objeto AuditRecord preexistente y programa su persistencia."""
        cid = self._resolve_correlation_id(correlation_id or record.correlation_id)
        if cid:
            record.correlation_id = cid
            if "correlation_id" not in record.details:
                record.details["correlation_id"] = cid
        self._history.append(record)
        self._schedule_persistence(record, execution_id)
        return record

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

    def get_history(self) -> list[AuditRecord]:
        """Retorna una copia inmutable del historial de auditoría en memoria."""
        return list(self._history)

    def clear(self) -> None:
        """Limpia el buffer de auditoría en memoria."""
        self._history.clear()

    @property
    def max_history(self) -> int | None:
        """Capacidad máxima configurada para el búfer circular en memoria."""
        return self._history.maxlen


_audit_lock = threading.Lock()
_default_audit_logger: SecurityAuditLogger | None = None


def get_security_audit_logger() -> SecurityAuditLogger:
    """Factory singleton thread-safe para obtener SecurityAuditLogger."""
    global _default_audit_logger
    if _default_audit_logger is None:
        with _audit_lock:
            if _default_audit_logger is None:
                _default_audit_logger = SecurityAuditLogger()
    return _default_audit_logger


# Alias canónico
get_audit_logger = get_security_audit_logger

__all__ = [
    "SecurityAuditLogger",
    "get_audit_logger",
    "get_security_audit_logger",
]
