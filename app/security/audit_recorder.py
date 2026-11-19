# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Subcomponente especializado en ingestión y formulación de registros de auditoría (SOLID/ISP)."""

import logging
from collections import deque
from collections.abc import Callable
from typing import Any

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

logger = logging.getLogger("jg_agente.security.audit_recorder")


class AuditRecorder:
    """Ingestor especializado en la recepción, logging y encolado de eventos de auditoría."""

    def __init__(
        self,
        history: deque[AuditRecord],
        schedule_persistence: Callable[[AuditRecord, str | None], None],
        resolve_correlation_id: Callable[[str | None], str | None],
    ) -> None:
        self._history = history
        self._schedule_persistence = schedule_persistence
        self._resolve_correlation_id = resolve_correlation_id

    def record(
        self,
        evaluation: SecurityEvaluationResult,
        execution_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra el resultado formal de una evaluación de seguridad."""
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
        rec = build_security_decision_record(evaluation, execution_id, cid)
        self._history.append(rec)
        self._schedule_persistence(rec, execution_id)
        return rec

    def record_stimulus(
        self,
        input_data: AgentInput,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra la recepción de un nuevo estímulo de entrada."""
        cid = self._resolve_correlation_id(
            correlation_id or input_data.correlation_id or input_data.metadata.get("correlation_id")
        )
        rec = build_stimulus_record(input_data, cid)
        self._history.append(rec)
        self._schedule_persistence(rec, input_data.execution_id)
        return rec

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
        """Registra la ejecución física o mock de una herramienta."""
        cid = self._resolve_correlation_id(correlation_id)
        rec = build_tool_execution_record(
            tool_name, tool_args, result, risk_level, execution_id, thread_id, cid
        )
        self._history.append(rec)
        self._schedule_persistence(rec, execution_id)
        return rec

    def record_state_transition(
        self,
        old_status: AgentExecutionStatus | str,
        new_status: AgentExecutionStatus | str,
        execution_id: str | None = None,
        thread_id: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra una transición de estado operacional."""
        cid = self._resolve_correlation_id(correlation_id)
        rec = build_state_transition_record(
            old_status, new_status, execution_id, thread_id, reason, cid
        )
        self._history.append(rec)
        self._schedule_persistence(rec, execution_id)
        return rec

    def record_approval(
        self,
        approval: ApprovalRecord,
        execution_id: str | None = None,
        thread_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Registra la solicitud o resolución de una aprobación humana (HITL)."""
        cid = self._resolve_correlation_id(correlation_id)
        rec = build_approval_record(approval, execution_id, thread_id, cid)
        self._history.append(rec)
        self._schedule_persistence(rec, execution_id)
        return rec

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
        """Registra un evento estructurado genérico."""
        cid = self._resolve_correlation_id(correlation_id or details.get("correlation_id"))
        rec = build_custom_event_record(
            event_type, details, actor, execution_id, risk_level, result, cid
        )
        self._history.append(rec)
        self._schedule_persistence(rec, execution_id)
        return rec

    def record_audit_record(
        self,
        record: AuditRecord,
        execution_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AuditRecord:
        """Ingesta un objeto AuditRecord preexistente."""
        cid = self._resolve_correlation_id(correlation_id or record.correlation_id)
        if cid:
            record.correlation_id = cid
            if "correlation_id" not in record.details:
                record.details["correlation_id"] = cid
        self._history.append(record)
        self._schedule_persistence(record, execution_id)
        return record


__all__ = ["AuditRecorder"]
