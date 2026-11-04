# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo de pausa HITL y reanudación (human_approval) para jg_agente.

Implementa la interrupción nativa de LangGraph mediante interrupt() para pausar la
ejecución de operaciones de riesgo, persistir el snapshot en el checkpointer y esperar
el comando externo de autorización o rechazo (Command(resume=...)) sin bloquear el proceso.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from app.core.registry import CapabilityRegistry
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

logger = logging.getLogger("jg_agente.nodes.human_approval")


async def human_approval_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Gestiona la pausa en checkpoint y la reanudación ante aprobación humana (HITL).

    Args:
        state: Estado global actual del agente (AgentState).
        registry: Catálogo de capacidades registrado opcional.

    Returns:
        Mutaciones del estado para LangGraph (status, human_intervention_required,
        requires_approval, approval, audit_trail).
    """
    start_time = time.perf_counter()

    # 1. Inspeccionar si la aprobación ya fue resuelta previamente
    raw_approval = state.get("approval")
    approval_rec: ApprovalRecord | None = None

    if isinstance(raw_approval, ApprovalRecord):
        approval_rec = raw_approval
    elif isinstance(raw_approval, dict):
        approval_rec = ApprovalRecord(**raw_approval)

    # 2. Si ya está aprobada para estos mismos pasos, continuar sin pausar
    current_required_steps = list(state.get("approved_step_ids") or [])
    is_step_subset_approved = True
    if (
        approval_rec is not None
        and approval_rec.approved_step_ids
        and current_required_steps
        and not set(current_required_steps).issubset(set(approval_rec.approved_step_ids))
    ):
        is_step_subset_approved = False

    if (
        approval_rec is not None
        and is_step_subset_approved
        and approval_rec.status
        in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.AUTO_APPROVED,
            ApprovalStatus.AUTO_APPROVED.value,
        )
    ):
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

    # 3. Si ya está rechazada, desviar hacia finalización
    if approval_rec is not None and approval_rec.status in (
        ApprovalStatus.REJECTED,
        ApprovalStatus.REJECTED.value,
    ):
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

    # 4. Preparar el payload de interrupción para exponer al cliente / Dashboard
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

    interrupt_payload: dict[str, Any] = {
        "action": "human_approval_required",
        "execution_id": execution_id,
        "thread_id": thread_id,
        "risk_assessment": risk_info,
        "plan": plan_info,
        "message": plan_info["warning_message"],
    }

    # 5. Invocar interrupt() de LangGraph
    decision: Any = None
    try:
        # LangGraph pausa aquí levantando GraphInterrupt y guardando checkpoint.
        # Al reanudar con Command(resume=...), interrupt() retorna el valor entregado.
        decision = interrupt(interrupt_payload)
    except RuntimeError as err:
        # Soporte para ejecuciones de test aisladas fuera de un contexto runnable de LangGraph
        logger.warning(
            "human_approval_node invocado fuera del contexto runnable de LangGraph: %s",
            err,
        )
        if approval_rec is None:
            approval_rec = ApprovalRecord(
                status=ApprovalStatus.PENDING,
                notes="Pausa HITL solicitada fuera de contexto runnable.",
            )
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "status": AgentExecutionStatus.AWAITING_APPROVAL,
            "human_intervention_required": True,
            "requires_approval": True,
            "approval": approval_rec,
            "audit_trail": [
                AuditRecord(
                    event_type="human_approval_requested",
                    actor="core",
                    details={
                        "status": approval_rec.status.value,
                        "offline": True,
                        "duration_ms": duration_ms,
                    },
                )
            ],
        }

    # 6. Procesar la decisión tras la reanudación (Resume)
    is_approved = False
    approver = "human_operator"
    notes = "Decisión recibida vía HITL resume"

    existing_steps = (
        raw_approval.approved_step_ids
        if isinstance(raw_approval, ApprovalRecord)
        else (raw_approval.get("approved_step_ids") if isinstance(raw_approval, dict) else [])
    ) or (state.get("approved_step_ids") or [])
    existing_tools = (
        raw_approval.approved_tool_names
        if isinstance(raw_approval, ApprovalRecord)
        else (raw_approval.get("approved_tool_names") if isinstance(raw_approval, dict) else [])
    ) or (state.get("approved_tool_names") or [])

    resumed_step_ids: list[str] = list(existing_steps)
    resumed_tool_names: list[str] = list(existing_tools)

    if isinstance(decision, ApprovalRecord):
        approval_rec = decision
        if decision.approved_step_ids:
            resumed_step_ids = list(decision.approved_step_ids)
        if decision.approved_tool_names:
            resumed_tool_names = list(decision.approved_tool_names)
        is_approved = approval_rec.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.AUTO_APPROVED,
            ApprovalStatus.AUTO_APPROVED.value,
        )
    elif isinstance(decision, dict):
        if decision.get("approved_step_ids"):
            resumed_step_ids = list(decision["approved_step_ids"])
        if decision.get("approved_tool_names"):
            resumed_tool_names = list(decision["approved_tool_names"])
        is_approved = bool(
            decision.get("approved")
            or decision.get("status")
            in (
                ApprovalStatus.APPROVED,
                ApprovalStatus.APPROVED.value,
                ApprovalStatus.AUTO_APPROVED,
                ApprovalStatus.AUTO_APPROVED.value,
                "approved",
                "APPROVED",
            )
        )
        approver = str(decision.get("approver") or "human_operator")
        notes = str(
            decision.get("notes")
            or decision.get("justification")
            or decision.get("reason")
            or ("Aprobado por operador" if is_approved else "Rechazado por operador")
        )
        approval_rec = ApprovalRecord(
            status=ApprovalStatus.APPROVED if is_approved else ApprovalStatus.REJECTED,
            approver=approver,
            notes=notes,
            approved_step_ids=resumed_step_ids if is_approved else [],
            approved_tool_names=resumed_tool_names if is_approved else [],
        )
    elif isinstance(decision, bool):
        is_approved = decision
        approval_rec = ApprovalRecord(
            status=ApprovalStatus.APPROVED if is_approved else ApprovalStatus.REJECTED,
            approver="human_operator",
            notes="Decisión booleana directa",
            approved_step_ids=resumed_step_ids if is_approved else [],
            approved_tool_names=resumed_tool_names if is_approved else [],
        )
    else:
        # Si la reanudación no aportó payload directo, verificar si el estado fue mutado externamente
        current_app = state.get("approval")
        if isinstance(current_app, ApprovalRecord) and current_app.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.APPROVED.value,
        ):
            approval_rec = current_app
            if current_app.approved_step_ids:
                resumed_step_ids = list(current_app.approved_step_ids)
            if current_app.approved_tool_names:
                resumed_tool_names = list(current_app.approved_tool_names)
            is_approved = True
        else:
            approval_rec = ApprovalRecord(
                status=ApprovalStatus.REJECTED,
                approver="system",
                notes="Reanudación sin autorización explícita.",
            )
            is_approved = False
            resumed_step_ids = []
            resumed_tool_names = []

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    final_status = AgentExecutionStatus.EXECUTING if is_approved else AgentExecutionStatus.FAILED

    cog_resumed = CognitiveStepRecord(
        step_id=f"cog_approval_{int(time.time() * 1000)}",
        node="human_approval",
        title="Control de Aprobación Humana (HITL)",
        action="Autorización Concedida" if is_approved else "Operación Denegada",
        description=(
            f"Operación {'autorizada' if is_approved else 'rechazada'} por "
            f"'{approval_rec.approver or approver}'. Motivo/Notas: {approval_rec.notes}"
        ),
        status="completed" if is_approved else "failed",
        details={
            "status": approval_rec.status.value,
            "approver": approval_rec.approver or approver,
            "notes": approval_rec.notes,
            "is_approved": is_approved,
        },
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )

    audit = AuditRecord(
        event_type="human_approval_completed" if is_approved else "human_approval_rejected",
        actor=approval_rec.approver or approver,
        details={
            "status": approval_rec.status.value,
            "approver": approval_rec.approver,
            "notes": approval_rec.notes,
            "is_approved": is_approved,
            "duration_ms": duration_ms,
        },
    )

    return {
        "status": final_status,
        "human_intervention_required": False,
        "requires_approval": False,
        "approval": approval_rec,
        "caller_permissions": resolve_caller_permissions(state),
        "approved_step_ids": resumed_step_ids if is_approved else [],
        "approved_tool_names": resumed_tool_names if is_approved else [],
        "cognitive_steps": [cog_resumed],
        "audit_trail": [audit],
    }
