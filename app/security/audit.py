"""Servicio de auditoría de seguridad inmutable para jg_agente.

Registra en la tabla core_audit_records de PostgreSQL y en memoria cada estímulo,
decisión de riesgo, ejecución de herramienta y cambio de estado, garantizando
persistencia no bloqueante para el ciclo asíncrono del agente.
"""

import asyncio
import logging
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.correlation import get_correlation_id
from app.db.models import CoreAuditRecord
from app.models.io import AgentInput, UserContext
from app.models.state import (
    AgentExecutionStatus,
    ApprovalRecord,
    AuditRecord,
    PolicyDecision,
    SecurityEvaluationResult,
)
from app.models.tools import RiskLevel, ToolResult

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
        if not self._auto_persist:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Si no hay bucle de eventos activo (ej. ejecución síncrona o tests simples), solo registrar en log
            logger.debug(
                "Sin event loop activo para persistir evento '%s' a BD. Almacenado en historial.",
                audit_record.event_type,
            )
            return

        task = loop.create_task(self._persist_to_db(audit_record, execution_id))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _persist_to_db(
        self,
        audit_record: AuditRecord,
        execution_id: str | None = None,
    ) -> None:
        """Escribe un registro de auditoría en la tabla core_audit_records."""
        try:
            async with self._session_factory() as session:
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
                    # Si falla por clave foránea (la ejecución aún no se ha creado en core_executions),
                    # se persiste sin FK directa para no perder la traza de auditoría.
                    err_str = str(integ_err).lower()
                    if execution_id and (
                        "foreign key" in err_str or "violates foreign key" in err_str
                    ):
                        logger.warning(
                            "execution_id '%s' no encontrado en core_executions. "
                            "Persistiendo evento '%s' desacoplado.",
                            execution_id,
                            audit_record.event_type,
                        )
                        details_copy = dict(audit_record.details)
                        details_copy["unlinked_execution_id"] = execution_id
                        fallback_record = CoreAuditRecord(
                            execution_id=None,
                            event_type=audit_record.event_type,
                            actor=audit_record.actor,
                            details=details_copy,
                            timestamp=audit_record.timestamp,
                        )
                        session.add(fallback_record)
                        await session.commit()
                    else:
                        raise
        except Exception as exc:
            logger.error(
                "Fallo persistiendo registro de auditoría '%s' en PostgreSQL: %s",
                audit_record.event_type,
                exc,
            )

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
        details: dict[str, Any] = {
            "decision": evaluation.decision.value,
            "operation": evaluation.operation,
            "target_resource": evaluation.target_resource,
            "risk_level": evaluation.risk_level.value,
            "reason": evaluation.reason,
            "required_permissions": evaluation.required_permissions,
            "is_reversible": evaluation.is_reversible,
            "can_cause_data_loss": evaluation.can_cause_data_loss,
            "result": evaluation.decision.value,
        }
        if cid:
            details["correlation_id"] = cid
        if execution_id:
            details["execution_id"] = execution_id

        record = AuditRecord(
            event_type="security_decision",
            actor="security_guard",
            details=details,
            correlation_id=cid,
            timestamp=evaluation.evaluated_at,
        )
        self._history.append(record)
        self._schedule_persistence(record, execution_id)
        return record

    def record_stimulus(
        self,
        input_data: AgentInput,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra la recepción de un nuevo estímulo de entrada (AgentInput)."""
        actor = "external_caller"
        if input_data.user_context:
            if isinstance(input_data.user_context, UserContext) and input_data.user_context.user_id:
                actor = input_data.user_context.user_id
            elif isinstance(input_data.user_context, dict) and input_data.user_context.get(
                "user_id"
            ):
                actor = str(input_data.user_context["user_id"])

        user_ctx_payload = (
            input_data.user_context.model_dump()
            if isinstance(input_data.user_context, UserContext)
            else input_data.user_context
        )

        cid = self._resolve_correlation_id(
            correlation_id or input_data.correlation_id or input_data.metadata.get("correlation_id")
        )
        details: dict[str, Any] = {
            "execution_id": input_data.execution_id,
            "thread_id": input_data.thread_id,
            "prompt": input_data.prompt,
            "parameters": input_data.parameters,
            "user_context": user_ctx_payload,
            "risk_level": RiskLevel.LOW.value,
            "result": "received",
        }
        if cid:
            details["correlation_id"] = cid

        record = AuditRecord(
            event_type="stimulus_received",
            actor=actor,
            details=details,
            correlation_id=cid,
            timestamp=datetime.now(UTC),
        )
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
        details: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "success": result.success,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "risk_level": risk_level.value,
            "result": "success" if result.success else "failed",
            "has_rollback": result.rollback_context is not None,
            "thread_id": thread_id,
        }
        if cid:
            details["correlation_id"] = cid
        if execution_id:
            details["execution_id"] = execution_id

        record = AuditRecord(
            event_type="tool_executed",
            actor="tool_executor",
            details=details,
            correlation_id=cid,
            timestamp=datetime.now(UTC),
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
        old_val = (
            old_status.value if isinstance(old_status, AgentExecutionStatus) else str(old_status)
        )
        new_val = (
            new_status.value if isinstance(new_status, AgentExecutionStatus) else str(new_status)
        )

        cid = self._resolve_correlation_id(correlation_id)
        details: dict[str, Any] = {
            "old_status": old_val,
            "new_status": new_val,
            "reason": reason,
            "thread_id": thread_id,
            "risk_level": RiskLevel.LOW.value,
            "result": "transitioned",
        }
        if cid:
            details["correlation_id"] = cid
        if execution_id:
            details["execution_id"] = execution_id

        record = AuditRecord(
            event_type="state_transition",
            actor="orchestrator",
            details=details,
            correlation_id=cid,
            timestamp=datetime.now(UTC),
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
        details: dict[str, Any] = {
            "status": approval.status.value,
            "approver": approval.approver,
            "notes": approval.notes,
            "rejection_reason": approval.rejection_reason,
            "risk_level": RiskLevel.HIGH.value,
            "result": approval.status.value,
            "thread_id": thread_id,
        }
        if cid:
            details["correlation_id"] = cid
        if execution_id:
            details["execution_id"] = execution_id

        record = AuditRecord(
            event_type="approval_decided",
            actor=approval.approver or "human_operator",
            details=details,
            correlation_id=cid,
            timestamp=approval.decided_at or datetime.now(UTC),
        )
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
        event_details = dict(details)
        cid = self._resolve_correlation_id(correlation_id or event_details.get("correlation_id"))
        if cid:
            event_details["correlation_id"] = cid

        if risk_level is not None:
            r_val = risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level)
            event_details["risk_level"] = r_val
        elif "risk_level" not in event_details:
            event_details["risk_level"] = RiskLevel.LOW.value

        if result is not None:
            event_details["result"] = result
        elif "result" not in event_details:
            event_details["result"] = "recorded"

        if execution_id:
            event_details["execution_id"] = execution_id

        record = AuditRecord(
            event_type=event_type,
            actor=actor,
            details=event_details,
            correlation_id=cid,
            timestamp=datetime.now(UTC),
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


# Instancia singleton perezosa y cerrojo de concurrencia
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
