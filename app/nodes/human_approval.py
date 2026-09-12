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

    # 2. Si ya está aprobada, continuar sin pausar
    if approval_rec is not None and approval_rec.status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.AUTO_APPROVED.value,
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

    plan = state.get("plan")
    plan_info = plan.model_dump() if isinstance(plan, ExecutionPlan) else plan
    risk_info = state.get("risk_assessment") or {}

    interrupt_payload: dict[str, Any] = {
        "action": "human_approval_required",
        "execution_id": execution_id,
        "thread_id": thread_id,
        "risk_assessment": risk_info,
        "plan": plan_info,
        "message": "Operación de alto riesgo detectada. Se requiere autorización humana en Dashboard.",
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

    if isinstance(decision, ApprovalRecord):
        approval_rec = decision
        is_approved = approval_rec.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.AUTO_APPROVED,
            ApprovalStatus.AUTO_APPROVED.value,
        )
    elif isinstance(decision, dict):
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
        )
    elif isinstance(decision, bool):
        is_approved = decision
        approval_rec = ApprovalRecord(
            status=ApprovalStatus.APPROVED if is_approved else ApprovalStatus.REJECTED,
            approver="human_operator",
            notes="Decisión booleana directa",
        )
    else:
        # Si la reanudación no aportó payload directo, verificar si el estado fue mutado externamente
        current_app = state.get("approval")
        if isinstance(current_app, ApprovalRecord) and current_app.status in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.APPROVED.value,
        ):
            approval_rec = current_app
            is_approved = True
        else:
            approval_rec = ApprovalRecord(
                status=ApprovalStatus.REJECTED,
                approver="system",
                notes="Reanudación sin autorización explícita.",
            )
            is_approved = False

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
        "cognitive_steps": [cog_resumed],
        "audit_trail": [audit],
    }
