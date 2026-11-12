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
    resolve_caller_permissions,
)
from app.nodes.human_approval_decision import parse_resume_decision
from app.nodes.human_approval_payload import (
    build_interrupt_payload,
    check_pre_resolved_approval,
)

logger = logging.getLogger("jg_agente.nodes.human_approval")

__all__ = ["human_approval_node"]


def _handle_test_offline_interrupt(
    state: AgentState,
    start_time: float,
) -> dict[str, Any]:
    """Fallback cuando human_approval_node es invocado fuera del contexto runnable de LangGraph."""
    raw_approval = state.get("approval")
    approval_rec = raw_approval if isinstance(raw_approval, ApprovalRecord) else None
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


async def human_approval_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Gestiona la pausa en checkpoint y la reanudación ante aprobación humana (HITL)."""
    start_time = time.perf_counter()

    pre_resolved = check_pre_resolved_approval(state, start_time)
    if pre_resolved is not None:
        return pre_resolved

    interrupt_payload = build_interrupt_payload(state)

    try:
        decision = interrupt(interrupt_payload)
    except RuntimeError as err:
        logger.warning(
            "human_approval_node invocado fuera del contexto runnable de LangGraph: %s", err
        )
        return _handle_test_offline_interrupt(state, start_time)

    is_approved, approval_rec, resumed_step_ids, resumed_tool_names = parse_resume_decision(
        decision, state
    )
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    final_status = AgentExecutionStatus.EXECUTING if is_approved else AgentExecutionStatus.FAILED

    cog_resumed = CognitiveStepRecord(
        step_id=f"cog_approval_{int(time.time() * 1000)}",
        node="human_approval",
        title="Control de Aprobación Humana (HITL)",
        action="Autorización Concedida" if is_approved else "Operación Denegada",
        description=(
            f"Operación {'autorizada' if is_approved else 'rechazada'} por "
            f"'{approval_rec.approver}'. Motivo/Notas: {approval_rec.notes}"
        ),
        status="completed" if is_approved else "failed",
        details={
            "status": approval_rec.status.value,
            "approver": approval_rec.approver,
            "notes": approval_rec.notes,
            "is_approved": is_approved,
        },
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )

    audit = AuditRecord(
        event_type="human_approval_completed" if is_approved else "human_approval_rejected",
        actor=approval_rec.approver or "human_operator",
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
