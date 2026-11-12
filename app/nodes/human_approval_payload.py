# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Construcción de payload de interrupción y comprobación de pre-aprobación HITL."""

import time
from datetime import UTC, datetime
from typing import Any

from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    AuditRecord,
    CognitiveStepRecord,
    ExecutionPlan,
    resolve_caller_permissions,
)


def check_pre_resolved_approval(
    state: AgentState,
    start_time: float,
) -> dict[str, Any] | None:
    """Verifica si la aprobación ya fue concedida o denegada previamente en el estado."""
    raw_approval = state.get("approval")
    approval_rec: ApprovalRecord | None = None

    if isinstance(raw_approval, ApprovalRecord):
        approval_rec = raw_approval
    elif isinstance(raw_approval, dict):
        approval_rec = ApprovalRecord(**raw_approval)

    if approval_rec is None:
        return None

    current_required_steps = list(state.get("approved_step_ids") or [])
    is_step_subset_approved = True
    if (
        approval_rec.approved_step_ids
        and current_required_steps
        and not set(current_required_steps).issubset(set(approval_rec.approved_step_ids))
    ):
        is_step_subset_approved = False

    is_approved = approval_rec.status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.AUTO_APPROVED.value,
    )

    if is_approved and is_step_subset_approved:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        cog_approved = CognitiveStepRecord(
            step_id=f"cog_approval_{int(time.time() * 1000)}",
            node="human_approval",
            title="Control de Aprobación Humana (HITL)",
            action="Autorización Concedida",
            description=(
                f"Operación autorizada por '{approval_rec.approver or 'human_operator'}'. "
                f"Notas: {approval_rec.notes}"
            ),
            status="completed",
            details={
                "status": approval_rec.status.value,
                "approver": approval_rec.approver,
                "notes": approval_rec.notes,
                "pre_approved": True,
            },
            duration_ms=duration_ms,
            timestamp=datetime.now(UTC),
        )
        return {
            "status": AgentExecutionStatus.EXECUTING,
            "human_intervention_required": False,
            "requires_approval": False,
            "approval": approval_rec,
            "caller_permissions": resolve_caller_permissions(state),
            "approved_step_ids": approval_rec.approved_step_ids
            or state.get("approved_step_ids")
            or [],
            "approved_tool_names": approval_rec.approved_tool_names
            or state.get("approved_tool_names")
            or [],
            "cognitive_steps": [cog_approved],
            "audit_trail": [
                AuditRecord(
                    event_type="human_approval_completed",
                    actor=approval_rec.approver or "human_operator",
                    details={
                        "status": approval_rec.status.value,
                        "approver": approval_rec.approver,
                        "notes": approval_rec.notes,
                        "pre_approved": True,
                        "duration_ms": duration_ms,
                    },
                )
            ],
        }

    if approval_rec.status in (ApprovalStatus.REJECTED, ApprovalStatus.REJECTED.value):
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        cog_rejected = CognitiveStepRecord(
            step_id=f"cog_approval_{int(time.time() * 1000)}",
            node="human_approval",
            title="Control de Aprobación Humana (HITL)",
            action="Operación Denegada",
            description=(
                f"Operación rechazada por '{approval_rec.approver or 'human_operator'}'. "
                f"Motivo: {approval_rec.notes}"
            ),
            status="failed",
            details={
                "status": approval_rec.status.value,
                "approver": approval_rec.approver,
                "notes": approval_rec.notes,
                "pre_rejected": True,
            },
            duration_ms=duration_ms,
            timestamp=datetime.now(UTC),
        )
        return {
            "status": AgentExecutionStatus.FAILED,
            "human_intervention_required": False,
            "requires_approval": False,
            "approval": approval_rec,
            "caller_permissions": resolve_caller_permissions(state),
            "cognitive_steps": [cog_rejected],
            "audit_trail": [
                AuditRecord(
                    event_type="human_approval_rejected",
                    actor=approval_rec.approver or "human_operator",
                    details={
                        "status": approval_rec.status.value,
                        "approver": approval_rec.approver,
                        "notes": approval_rec.notes,
                        "pre_rejected": True,
                        "duration_ms": duration_ms,
                    },
                )
            ],
        }

    return None


def build_interrupt_payload(state: AgentState) -> dict[str, Any]:
    """Genera el payload descriptivo para interrupt() que consumirá el Dashboard/cliente."""
    req = state.get("request")
    execution_id = getattr(req, "execution_id", None) if req else None
    thread_id = getattr(req, "thread_id", None) if req else None
    prompt_val = getattr(req, "prompt", None) if req else None

    plan = state.get("plan")
    plan_info: dict[str, Any] | None = (
        plan.model_dump(mode="json")
        if isinstance(plan, ExecutionPlan)
        else (dict(plan) if isinstance(plan, dict) else None)
    )
    risk_info = state.get("risk_assessment") or {}
    evaluated_steps: list[dict[str, Any]] = (
        list(risk_info.get("plan_steps") or []) if isinstance(risk_info, dict) else []
    )

    if plan_info is None:
        plan_info = {
            "goal": prompt_val or "Plan de acción propuesto",
            "estimated_risk": (
                str(risk_info.get("risk_level", "HIGH")).upper()
                if isinstance(risk_info, dict)
                else "HIGH"
            ),
            "steps": evaluated_steps,
        }
    elif evaluated_steps:
        plan_info["steps"] = evaluated_steps

    steps_in_plan = plan_info.get("steps") or []
    mutative_count = sum(
        1
        for s in steps_in_plan
        if isinstance(s, dict)
        and (
            s.get("mutative") is True
            or s.get("read_only") is False
            or str(s.get("risk_level", "")).upper() in ("HIGH", "CRITICAL", "MEDIUM")
        )
    )
    total_count = len(steps_in_plan)
    plan_info["mutative_steps_count"] = mutative_count
    plan_info["total_steps_count"] = total_count
    plan_info["warning_message"] = (
        f"AVISO DE GOBERNANZA HITL: Con esta aprobación se autoriza la ejecución del plan de acción completo "
        f"({total_count} etapa(s) en total, de las cuales {mutative_count} son ETAPAS MUTATIVAS marcadas en rojo). "
        f"Revisa todas las etapas antes de conceder la autorización."
    )

    return {
        "action": "human_approval_required",
        "execution_id": execution_id,
        "thread_id": thread_id,
        "risk_assessment": risk_info,
        "plan": plan_info,
        "message": plan_info["warning_message"],
    }
