# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Procesamiento y normalización de la decisión de reanudación (Resume) tras pausa HITL."""

from typing import Any

from app.models.state import AgentState, ApprovalRecord, ApprovalStatus


def _extract_existing_step_and_tool_names(
    state: AgentState,
    raw_approval: Any,
) -> tuple[list[str], list[str]]:
    """Recupera listas existentes de pasos y herramientas previamente autorizadas."""
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

    return list(existing_steps), list(existing_tools)


def parse_resume_decision(
    decision: Any,
    state: AgentState,
) -> tuple[bool, ApprovalRecord, list[str], list[str]]:
    """Normaliza el payload recibido por Command(resume=...) a un ApprovalRecord canónico."""
    raw_approval = state.get("approval")
    resumed_step_ids, resumed_tool_names = _extract_existing_step_and_tool_names(
        state, raw_approval
    )

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
        return is_approved, approval_rec, resumed_step_ids, resumed_tool_names

    if isinstance(decision, dict):
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
        return is_approved, approval_rec, resumed_step_ids, resumed_tool_names

    if isinstance(decision, bool):
        is_approved = decision
        approval_rec = ApprovalRecord(
            status=ApprovalStatus.APPROVED if is_approved else ApprovalStatus.REJECTED,
            approver="human_operator",
            notes="Decisión booleana directa",
            approved_step_ids=resumed_step_ids if is_approved else [],
            approved_tool_names=resumed_tool_names if is_approved else [],
        )
        return is_approved, approval_rec, resumed_step_ids, resumed_tool_names

    current_app = state.get("approval")
    if isinstance(current_app, ApprovalRecord) and current_app.status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
    ):
        if current_app.approved_step_ids:
            resumed_step_ids = list(current_app.approved_step_ids)
        if current_app.approved_tool_names:
            resumed_tool_names = list(current_app.approved_tool_names)
        return True, current_app, resumed_step_ids, resumed_tool_names

    fallback_rec = ApprovalRecord(
        status=ApprovalStatus.REJECTED,
        approver="system",
        notes="Reanudación sin autorización explícita.",
    )
    return False, fallback_rec, [], []
