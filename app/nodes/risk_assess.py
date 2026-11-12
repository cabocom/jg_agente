# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo de evaluación de riesgo y política HITL (risk_assess) para jg_agente.

Analiza las acciones previstas en el plan estructurado (ExecutionPlan) o las llamadas
a herramientas (tool_calls), evaluando permisos, directivas de red e inyecciones
mediante SecurityGuard. Si alguna acción presenta RiskLevel >= HIGH, marca requires_approval=True
y deriva la ejecución hacia la puerta de aprobación humana (human_approval).
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    AuditRecord,
    CognitiveStepRecord,
    PolicyDecision,
    SecurityEvaluationResult,
    resolve_caller_permissions,
)
from app.nodes.risk_assess_evaluator import (
    _RISK_ORDER,
    collect_steps_to_evaluate,
    evaluate_steps_risk,
)
from app.security.guard import SecurityGuard, get_security_guard

logger = logging.getLogger("jg_agente.nodes.risk_assess")

__all__ = ["risk_assess_node", "_RISK_ORDER"]


def _resolve_approval_record(
    state: AgentState,
    reason: str,
    steps_requiring_approval: list[str],
    tools_requiring_approval: list[str],
) -> ApprovalRecord | None:
    """Verifica si el estado ya contaba con aprobación válida o crea un ApprovalRecord PENDING."""
    current_approval = state.get("approval")
    current_status = None
    existing_approved_steps: list[str] = []
    if isinstance(current_approval, ApprovalRecord):
        current_status = current_approval.status
        existing_approved_steps = list(current_approval.approved_step_ids or [])
    elif isinstance(current_approval, dict):
        current_status = current_approval.get("status")
        existing_approved_steps = list(current_approval.get("approved_step_ids") or [])

    is_already_approved = current_status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.AUTO_APPROVED.value,
    )
    if (
        is_already_approved
        and existing_approved_steps
        and steps_requiring_approval
        and not set(steps_requiring_approval).issubset(set(existing_approved_steps))
    ):
        is_already_approved = False

    if not is_already_approved:
        return ApprovalRecord(
            status=ApprovalStatus.PENDING,
            notes=reason,
            approved_step_ids=steps_requiring_approval,
            approved_tool_names=tools_requiring_approval,
        )
    return None


async def risk_assess_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
    security_guard: SecurityGuard | None = None,
) -> dict[str, Any]:
    """Evalúa las políticas de riesgo operacional y gobernanza HITL antes de ejecutar herramientas."""
    start_time = time.perf_counter()
    guard = security_guard or get_security_guard()
    checkpoint_degraded = bool(state.get("checkpoint_degraded", False))
    caller_perms = resolve_caller_permissions(state)

    req = state.get("request")
    execution_id = getattr(req, "execution_id", None) if req else None

    steps_to_evaluate = collect_steps_to_evaluate(state)
    (
        decision,
        reason,
        max_risk,
        requires_approval,
        has_data_loss,
        denied_reasons,
        approval_reasons,
        steps_req_approval,
        tools_req_approval,
        evaluated_plan_steps,
    ) = evaluate_steps_risk(
        steps_to_evaluate=steps_to_evaluate,
        registry=registry,
        guard=guard,
        caller_perms=caller_perms,
        execution_id=execution_id,
        checkpoint_degraded=checkpoint_degraded,
    )

    eval_result = SecurityEvaluationResult(
        decision=decision,
        operation="risk_assessment",
        target_resource="execution_plan" if state.get("plan") else "tool_calls",
        risk_level=max_risk,
        reason=reason,
        can_cause_data_loss=has_data_loss,
    )

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    step_status = "completed"
    if decision == PolicyDecision.DENY:
        step_status = "failed"
    elif decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL:
        step_status = "waiting_approval"

    cognitive_step = CognitiveStepRecord(
        step_id=f"cog_risk_assess_{int(time.time() * 1000)}",
        node="risk_assess",
        title="Evaluación de Riesgo y Gobernanza (SecurityGuard)",
        action=f"Análisis de Política ({decision.value.upper()})",
        description=f"Evaluación completada con veredicto '{decision.value.upper()}' (Riesgo: {max_risk.value.upper()}). {reason}",
        status=step_status,
        details={
            "decision": decision.value,
            "max_risk": max_risk.value,
            "requires_approval": requires_approval,
            "steps_evaluated": len(steps_to_evaluate),
            "denied_reasons": denied_reasons,
            "approval_reasons": approval_reasons,
        },
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )

    risk_assessment_payload = eval_result.model_dump()
    risk_assessment_payload["plan_steps"] = evaluated_plan_steps
    risk_assessment_payload["mutative_steps_count"] = sum(
        1 for s in evaluated_plan_steps if s.get("mutative")
    )
    risk_assessment_payload["total_steps_count"] = len(evaluated_plan_steps)

    update_state: dict[str, Any] = {
        "caller_permissions": caller_perms,
        "risk_assessment": risk_assessment_payload,
        "requires_approval": requires_approval,
        "human_intervention_required": requires_approval,
        "circuit_breaker_active": decision == PolicyDecision.DENY,
        "checkpoint_degraded": checkpoint_degraded,
        "cognitive_steps": [cognitive_step],
        "audit_trail": [
            AuditRecord(
                event_type="risk_assessment_completed",
                actor="security_guard",
                details={
                    "decision": decision.value,
                    "risk_level": max_risk.value,
                    "requires_approval": requires_approval,
                    "duration_ms": duration_ms,
                },
            )
        ],
    }

    if requires_approval:
        update_state["status"] = AgentExecutionStatus.AWAITING_APPROVAL
        update_state["approved_step_ids"] = steps_req_approval
        update_state["approved_tool_names"] = tools_req_approval
        appr_rec = _resolve_approval_record(state, reason, steps_req_approval, tools_req_approval)
        if appr_rec is not None:
            update_state["approval"] = appr_rec
    elif decision == PolicyDecision.DENY:
        update_state["status"] = AgentExecutionStatus.FAILED

    return update_state
