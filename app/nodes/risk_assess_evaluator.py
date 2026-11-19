# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Extracción y evaluación de riesgo operacional mediante SecurityGuard."""

from typing import Any

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentState,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    PolicyDecision,
)
from app.models.tools import RiskLevel
from app.security.guard import SecurityGuard

_RISK_ORDER: dict[RiskLevel | str, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


def collect_steps_to_evaluate(state: AgentState) -> list[PlanStep]:
    """Recolecta los pasos a evaluar desde el plan o llamadas directas a herramientas."""
    plan = state.get("plan")
    if isinstance(plan, ExecutionPlan):
        return list(plan.steps)
    if isinstance(plan, dict) and "steps" in plan:
        return [PlanStep(**s) if isinstance(s, dict) else s for s in plan.get("steps", [])]

    # Metadatos previos generados en HITL expansion
    meta_by_id: dict[str, dict[str, Any]] = {}
    intent_obj = state.get("intent")
    if isinstance(intent_obj, IntentModel):
        for m in intent_obj.parameters.get("plan_steps_metadata") or []:
            if isinstance(m, dict) and m.get("step_id"):
                meta_by_id[str(m["step_id"])] = m
    elif isinstance(intent_obj, dict):
        for m in (intent_obj.get("parameters") or {}).get("plan_steps_metadata") or []:
            if isinstance(m, dict) and m.get("step_id"):
                meta_by_id[str(m["step_id"])] = m

    tcs: list[dict[str, Any]] = []
    if isinstance(intent_obj, IntentModel):
        tcs = intent_obj.parameters.get("tool_calls") or []
    elif isinstance(intent_obj, dict):
        tcs = (intent_obj.get("parameters") or {}).get("tool_calls") or []

    if not tcs:
        messages = state.get("messages") or []
        if messages:
            last_msg = messages[-1]
            tcs = getattr(last_msg, "tool_calls", None) or []

    steps: list[PlanStep] = []
    for idx, tc in enumerate(tcs, start=1):
        tc_id = tc.get("id") or f"call_{idx}"
        tc_name = tc.get("name") or tc.get("tool_name", f"tool-{idx}")
        tc_args = tc.get("args") or tc.get("tool_args", {})
        meta_desc = (meta_by_id.get(tc_id) or {}).get("description")
        steps.append(
            PlanStep(
                step_id=tc_id,
                tool_name=tc_name,
                tool_args=tc_args,
                description=str(meta_desc) if meta_desc else f"Ejecutar {tc_name}",
                risk_level=RiskLevel.LOW,
            )
        )
    return steps


def _step_label(s: PlanStep) -> str:
    """Etiqueta descriptiva para visualización en el veredicto."""
    args = s.tool_args if isinstance(s.tool_args, dict) else {}
    cmd = (
        args.get("command")
        or args.get("target_url")
        or args.get("url")
        or args.get("target")
        or args.get("query")
    )
    return f"{s.tool_name} ('{cmd}')" if cmd else s.tool_name


def _evaluate_single_step(
    idx: int,
    step: PlanStep,
    registry: CapabilityRegistry | None,
    guard: SecurityGuard,
    caller_perms: list[str],
    execution_id: str | None,
    checkpoint_degraded: bool,
) -> tuple[dict[str, Any], RiskLevel, Any, bool, str]:
    """Evalúa las políticas de riesgo y construye metadatos para un paso unitario."""
    tool = registry.get_tool(step.tool_name) if registry else None
    effective_risk = tool.risk_level if tool else step.risk_level
    eval_res = guard.evaluate(
        tool=tool or step.tool_name,
        tool_args=step.tool_args,
        risk_level=effective_risk,
        caller_permissions=caller_perms,
        is_reversible=tool.reversible if tool else step.reversible,
        execution_id=execution_id,
        checkpoint_degraded=checkpoint_degraded,
    )
    is_mutative = (
        (not getattr(tool, "read_only", True))
        if tool is not None
        else effective_risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
    ) or effective_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    args_dict = step.tool_args if isinstance(step.tool_args, dict) else {}
    cmd = (
        args_dict.get("command")
        or args_dict.get("target_url")
        or args_dict.get("url")
        or args_dict.get("target")
        or args_dict.get("container")
        or args_dict.get("query")
        or ""
    )
    desc = step.description or ""
    if not desc or desc == f"Ejecutar {step.tool_name}":
        desc = (
            f"{'Mutación' if is_mutative else 'Consulta'} con {step.tool_name}: {cmd}"
            if cmd
            else f"Ejecutar {step.tool_name}"
        )
    step_meta = {
        "index": idx,
        "step_id": step.step_id,
        "tool_name": step.tool_name,
        "tool": step.tool_name,
        "command": str(cmd) if cmd else None,
        "action": desc,
        "description": desc,
        "risk_level": effective_risk.value.upper(),
        "mutative": is_mutative,
        "read_only": not is_mutative,
        "reversible": bool(tool.reversible if tool else step.reversible),
    }
    tool_name_entry = tool.name if tool else step.tool_name
    return step_meta, effective_risk, eval_res, is_mutative, tool_name_entry


def _aggregate_risk_verdict(
    steps_to_evaluate: list[PlanStep],
    denied_reasons: list[str],
    approval_reasons: list[str],
    requires_approval: bool,
    max_risk: RiskLevel,
) -> tuple[PolicyDecision, str]:
    """Determina la decisión y justificación global consolidada."""
    if denied_reasons:
        return PolicyDecision.DENY, " ; ".join(denied_reasons)
    if requires_approval:
        return PolicyDecision.REQUIRE_HUMAN_APPROVAL, " ; ".join(approval_reasons)
    labels = ", ".join(_step_label(s) for s in steps_to_evaluate)
    return (
        PolicyDecision.ALLOW,
        f"Operación [{labels}] con nivel de riesgo operativo aceptable ({max_risk.value.upper()}) para ejecución autónoma.",
    )


def evaluate_steps_risk(
    steps_to_evaluate: list[PlanStep],
    registry: CapabilityRegistry | None,
    guard: SecurityGuard,
    caller_perms: list[str],
    execution_id: str | None,
    checkpoint_degraded: bool,
) -> tuple[
    PolicyDecision,
    str,
    RiskLevel,
    bool,
    bool,
    list[str],
    list[str],
    list[str],
    list[str],
    list[dict[str, Any]],
]:
    """Evalúa secuencialmente las políticas de riesgo sobre cada paso formulado."""
    max_risk = RiskLevel.LOW
    requires_approval = False
    has_data_loss = False
    denied_reasons: list[str] = []
    approval_reasons: list[str] = []
    steps_requiring_approval: list[str] = []
    tools_requiring_approval: list[str] = []
    evaluated_plan_steps: list[dict[str, Any]] = []

    if not steps_to_evaluate:
        return (
            PolicyDecision.ALLOW,
            "No se detectaron operaciones que requieran evaluación de riesgo.",
            max_risk,
            requires_approval,
            has_data_loss,
            denied_reasons,
            approval_reasons,
            steps_requiring_approval,
            tools_requiring_approval,
            evaluated_plan_steps,
        )

    for idx, step in enumerate(steps_to_evaluate, start=1):
        meta, eff_risk, eval_res, _, t_name = _evaluate_single_step(
            idx, step, registry, guard, caller_perms, execution_id, checkpoint_degraded
        )
        if _RISK_ORDER.get(eff_risk, 1) > _RISK_ORDER.get(max_risk, 1):
            max_risk = eff_risk
        evaluated_plan_steps.append(meta)

        if eval_res.decision == PolicyDecision.DENY:
            denied_reasons.append(
                f"Acción denegada '{step.tool_name}': {eval_res.reason or 'Violación de seguridad'}"
            )
        if eval_res.decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL or eff_risk in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        ):
            requires_approval = True
            steps_requiring_approval.append(step.step_id)
            if t_name and t_name not in tools_requiring_approval:
                tools_requiring_approval.append(t_name)
            approval_reasons.append(
                f"Acción '{step.tool_name}' ({eff_risk.value.upper()}): {eval_res.reason}"
            )
            if eval_res.can_cause_data_loss or eff_risk == RiskLevel.CRITICAL:
                has_data_loss = True

    decision, reason = _aggregate_risk_verdict(
        steps_to_evaluate, denied_reasons, approval_reasons, requires_approval, max_risk
    )
    return (
        decision,
        reason,
        max_risk,
        requires_approval,
        has_data_loss,
        denied_reasons,
        approval_reasons,
        steps_requiring_approval,
        tools_requiring_approval,
        evaluated_plan_steps,
    )
