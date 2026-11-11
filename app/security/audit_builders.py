# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Constructores de registros de auditoría estructurados (AuditRecord)."""

from datetime import UTC, datetime
from typing import Any

from app.models.io import AgentInput, UserContext
from app.models.state import (
    AgentExecutionStatus,
    ApprovalRecord,
    AuditRecord,
    SecurityEvaluationResult,
)
from app.models.tools import RiskLevel, ToolResult


def build_security_decision_record(
    evaluation: SecurityEvaluationResult,
    execution_id: str | None = None,
    correlation_id: str | None = None,
) -> AuditRecord:
    """Construye un AuditRecord a partir de un SecurityEvaluationResult."""
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
    if correlation_id:
        details["correlation_id"] = correlation_id
    if execution_id:
        details["execution_id"] = execution_id

    return AuditRecord(
        event_type="security_decision",
        actor="security_guard",
        details=details,
        correlation_id=correlation_id,
        timestamp=evaluation.evaluated_at,
    )


def build_stimulus_record(
    input_data: AgentInput,
    correlation_id: str | None = None,
) -> AuditRecord:
    """Construye un AuditRecord a partir de un estímulo entrante (AgentInput)."""
    actor = "external_caller"
    if input_data.user_context:
        if isinstance(input_data.user_context, UserContext) and input_data.user_context.user_id:
            actor = input_data.user_context.user_id
        elif isinstance(input_data.user_context, dict) and input_data.user_context.get("user_id"):
            actor = str(input_data.user_context["user_id"])

    user_ctx_payload = (
        input_data.user_context.model_dump()
        if isinstance(input_data.user_context, UserContext)
        else input_data.user_context
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
    if correlation_id:
        details["correlation_id"] = correlation_id

    return AuditRecord(
        event_type="stimulus_received",
        actor=actor,
        details=details,
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )


def build_tool_execution_record(
    tool_name: str,
    tool_args: dict[str, Any],
    result: ToolResult,
    risk_level: RiskLevel = RiskLevel.LOW,
    execution_id: str | None = None,
    thread_id: str | None = None,
    correlation_id: str | None = None,
) -> AuditRecord:
    """Construye un AuditRecord para la ejecución de una herramienta."""
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
    if correlation_id:
        details["correlation_id"] = correlation_id
    if execution_id:
        details["execution_id"] = execution_id

    return AuditRecord(
        event_type="tool_executed",
        actor="tool_executor",
        details=details,
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )


def build_state_transition_record(
    old_status: AgentExecutionStatus | str,
    new_status: AgentExecutionStatus | str,
    execution_id: str | None = None,
    thread_id: str | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> AuditRecord:
    """Construye un AuditRecord para transiciones de estado del ciclo de vida."""
    old_val = old_status.value if isinstance(old_status, AgentExecutionStatus) else str(old_status)
    new_val = new_status.value if isinstance(new_status, AgentExecutionStatus) else str(new_status)

    details: dict[str, Any] = {
        "old_status": old_val,
        "new_status": new_val,
        "reason": reason,
        "thread_id": thread_id,
        "risk_level": RiskLevel.LOW.value,
        "result": "transitioned",
    }
    if correlation_id:
        details["correlation_id"] = correlation_id
    if execution_id:
        details["execution_id"] = execution_id

    return AuditRecord(
        event_type="state_transition",
        actor="orchestrator",
        details=details,
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )


def build_approval_record(
    approval: ApprovalRecord,
    execution_id: str | None = None,
    thread_id: str | None = None,
    correlation_id: str | None = None,
) -> AuditRecord:
    """Construye un AuditRecord para resoluciones HITL."""
    details: dict[str, Any] = {
        "status": approval.status.value,
        "approver": approval.approver,
        "notes": approval.notes,
        "rejection_reason": approval.rejection_reason,
        "risk_level": RiskLevel.HIGH.value,
        "result": approval.status.value,
        "thread_id": thread_id,
    }
    if correlation_id:
        details["correlation_id"] = correlation_id
    if execution_id:
        details["execution_id"] = execution_id

    return AuditRecord(
        event_type="approval_decided",
        actor=approval.approver or "human_operator",
        details=details,
        correlation_id=correlation_id,
        timestamp=approval.decided_at or datetime.now(UTC),
    )


def build_custom_event_record(
    event_type: str,
    details: dict[str, Any],
    actor: str = "agent",
    execution_id: str | None = None,
    risk_level: RiskLevel | str | None = None,
    result: Any = None,
    correlation_id: str | None = None,
) -> AuditRecord:
    """Construye un AuditRecord para eventos genéricos."""
    event_details = dict(details)
    if correlation_id:
        event_details["correlation_id"] = correlation_id

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

    return AuditRecord(
        event_type=event_type,
        actor=actor,
        details=event_details,
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )
