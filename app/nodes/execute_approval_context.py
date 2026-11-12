# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Resolución de aprobaciones HITL, contexto y extracción de pasos a ejecutar."""

import json
from typing import Any

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    resolve_caller_permissions,
)
from app.models.tools import RiskLevel


def resolve_execution_context(
    state: AgentState,
) -> tuple[str | None, str | None, bool, set[str], set[str], list[str]]:
    """Resuelve IDs de ejecución, permisos y estado de aprobación HITL granular."""
    execution_id: str | None = None
    thread_id: str | None = None
    req = state.get("request")
    if req:
        execution_id = getattr(req, "execution_id", None)
        thread_id = getattr(req, "thread_id", None)

    approval_val = state.get("approval")
    approval_status: ApprovalStatus | str | None = None
    approved_step_ids: set[str] = set()
    approved_tool_names: set[str] = set()

    if isinstance(approval_val, ApprovalRecord):
        approval_status = approval_val.status
        if approval_val.approved_step_ids:
            approved_step_ids.update(approval_val.approved_step_ids)
        if approval_val.approved_tool_names:
            approved_tool_names.update(approval_val.approved_tool_names)
    elif isinstance(approval_val, dict):
        approval_status = approval_val.get("status")
        if approval_val.get("approved_step_ids"):
            approved_step_ids.update(approval_val["approved_step_ids"])
        if approval_val.get("approved_tool_names"):
            approved_tool_names.update(approval_val["approved_tool_names"])

    state_steps = state.get("approved_step_ids")
    if state_steps:
        approved_step_ids.update(state_steps)
    state_tools = state.get("approved_tool_names")
    if state_tools:
        approved_tool_names.update(state_tools)

    is_plan_approved = approval_status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.AUTO_APPROVED.value,
    )
    caller_perms = resolve_caller_permissions(state)

    return (
        execution_id,
        thread_id,
        is_plan_approved,
        approved_step_ids,
        approved_tool_names,
        caller_perms,
    )


def _extract_steps_from_tool_calls(
    state: AgentState,
    registry: CapabilityRegistry,
) -> list[PlanStep]:
    """Extrae PlanStep a partir de llamadas directas a herramientas (tool_calls)."""
    intent_val = state.get("intent")
    tool_calls: list[dict[str, Any]] = []
    if isinstance(intent_val, IntentModel) and intent_val.parameters:
        tool_calls = intent_val.parameters.get("tool_calls", [])
    elif isinstance(intent_val, dict) and "parameters" in intent_val:
        tool_calls = intent_val.get("parameters", {}).get("tool_calls", [])

    steps_to_run: list[PlanStep] = []
    for idx, tc in enumerate(tool_calls, start=1):
        call_id = tc.get("id") or f"call_{idx}"
        name = tc.get("name", "")
        args = tc.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"input": args}
        tool_def = registry.get_tool(name)
        risk = tool_def.risk_level if tool_def else RiskLevel.LOW
        rev = tool_def.reversible if tool_def else False
        steps_to_run.append(
            PlanStep(
                step_id=call_id,
                tool_name=name,
                tool_args=args,
                description=f"Ejecución directa de {name}",
                risk_level=risk,
                reversible=rev,
            )
        )
    return steps_to_run


def resolve_steps_to_run(
    state: AgentState,
    registry: CapabilityRegistry,
) -> tuple[ExecutionPlan | None, list[PlanStep]]:
    """Determina los pasos a ejecutar desde el plan estructurado o desde tool_calls directas."""
    raw_plan = state.get("plan")
    plan: ExecutionPlan | None = None
    steps_to_run: list[PlanStep] = []

    if isinstance(raw_plan, ExecutionPlan):
        plan = raw_plan
        steps_to_run = list(plan.steps)
    elif isinstance(raw_plan, dict) and "steps" in raw_plan:
        plan = ExecutionPlan(**raw_plan)
        steps_to_run = list(plan.steps)

    if not steps_to_run:
        steps_to_run = _extract_steps_from_tool_calls(state, registry)

    return plan, steps_to_run
