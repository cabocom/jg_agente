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
    ExecutionPlan,
    IntentModel,
    PlanStep,
    PolicyDecision,
    SecurityEvaluationResult,
    resolve_caller_permissions,
)
from app.models.tools import RiskLevel
from app.security.guard import SecurityGuard, get_security_guard

logger = logging.getLogger("jg_agente.nodes.risk_assess")

_RISK_ORDER: dict[RiskLevel | str, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


async def risk_assess_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
    security_guard: SecurityGuard | None = None,
) -> dict[str, Any]:
    """Evalúa las políticas de riesgo operacional y gobernanza HITL antes de ejecutar herramientas.

    Args:
        state: Estado global actual del agente (AgentState).
        registry: Catálogo de capacidades registrado opcional.
        security_guard: Interceptor de seguridad opcional (usa singleton si es None).

    Returns:
        Mutaciones de estado para LangGraph (risk_assessment, requires_approval,
        human_intervention_required, status, approval, circuit_breaker_active, audit_trail).
    """
    start_time = time.perf_counter()
    guard = security_guard or get_security_guard()
    checkpoint_degraded = bool(state.get("checkpoint_degraded", False))

    # 1. Extraer identificador de ejecución para trazabilidad en auditoría
    req = state.get("request")
    execution_id = getattr(req, "execution_id", None) if req else None

    # 2. Recolectar acciones u operaciones previstas a evaluar
    steps_to_evaluate: list[PlanStep] = []
    plan = state.get("plan")

    if isinstance(plan, ExecutionPlan):
        steps_to_evaluate = list(plan.steps)
    elif isinstance(plan, dict) and "steps" in plan:
        steps_to_evaluate = [
            PlanStep(**s) if isinstance(s, dict) else s for s in plan.get("steps", [])
        ]

    # Si no hay plan estructurado, buscar tool_calls directas en intent o mensajes
    plan_steps_meta_by_id: dict[str, dict[str, Any]] = {}
    intent_obj = state.get("intent")
    if isinstance(intent_obj, IntentModel):
        for m in intent_obj.parameters.get("plan_steps_metadata") or []:
            if isinstance(m, dict) and m.get("step_id"):
                plan_steps_meta_by_id[str(m["step_id"])] = m
    elif isinstance(intent_obj, dict):
        for m in (intent_obj.get("parameters") or {}).get("plan_steps_metadata") or []:
            if isinstance(m, dict) and m.get("step_id"):
                plan_steps_meta_by_id[str(m["step_id"])] = m

    if not steps_to_evaluate:
        tcs: list[dict[str, Any]] = []
        intent = state.get("intent")
        if isinstance(intent, IntentModel):
            tcs = intent.parameters.get("tool_calls") or []
        elif isinstance(intent, dict):
            params = intent.get("parameters") or {}
            tcs = params.get("tool_calls") or []

        if not tcs:
            messages = state.get("messages") or []
            if messages:
                last_msg = messages[-1]
                tcs = getattr(last_msg, "tool_calls", None) or []

        for idx, tc in enumerate(tcs, start=1):
            tc_id = tc.get("id") or f"call_{idx}"
            tc_name = tc.get("name") or tc.get("tool_name", f"tool-{idx}")
            tc_args = tc.get("args") or tc.get("tool_args", {})
            meta_desc = (plan_steps_meta_by_id.get(tc_id) or {}).get("description")
            steps_to_evaluate.append(
                PlanStep(
                    step_id=tc_id,
                    tool_name=tc_name,
                    tool_args=tc_args,
                    description=str(meta_desc) if meta_desc else f"Ejecutar {tc_name}",
                    risk_level=RiskLevel.LOW,
                )
            )

    # 3. Evaluar cada acción mediante SecurityGuard
    max_risk = RiskLevel.LOW
    requires_approval = False
    has_data_loss = False
    denied_reasons: list[str] = []
    approval_reasons: list[str] = []
    steps_requiring_approval: list[str] = []
    tools_requiring_approval: list[str] = []
    evaluated_plan_steps: list[dict[str, Any]] = []

    caller_perms = resolve_caller_permissions(state)

    if not steps_to_evaluate:
        decision = PolicyDecision.ALLOW
        reason = "No se detectaron operaciones que requieran evaluación de riesgo."
    else:
        for idx, step in enumerate(steps_to_evaluate, start=1):
            tool = registry.get_tool(step.tool_name) if registry else None
            effective_risk = tool.risk_level if tool else step.risk_level

            # Actualizar máximo riesgo observado
            if _RISK_ORDER.get(effective_risk, 1) > _RISK_ORDER.get(max_risk, 1):
                max_risk = effective_risk

            # Evaluar con SecurityGuard
            eval_res = guard.evaluate(
                tool=tool or step.tool_name,
                tool_args=step.tool_args,
                risk_level=effective_risk,
                caller_permissions=caller_perms,
                is_reversible=tool.reversible if tool else step.reversible,
                execution_id=execution_id,
                checkpoint_degraded=checkpoint_degraded,
            )

            is_step_mutative = (
                (not getattr(tool, "read_only", True))
                if tool is not None
                else effective_risk in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
            ) or effective_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)

            args_dict = step.tool_args if isinstance(step.tool_args, dict) else {}
            cmd_val = (
                args_dict.get("command")
                or args_dict.get("target_url")
                or args_dict.get("url")
                or args_dict.get("target")
                or args_dict.get("container")
                or args_dict.get("query")
                or ""
            )
            step_desc = step.description or ""
            if not step_desc or step_desc == f"Ejecutar {step.tool_name}":
                if cmd_val:
                    step_desc = f"{'Mutación' if is_step_mutative else 'Consulta'} con {step.tool_name}: {cmd_val}"
                else:
                    step_desc = f"Ejecutar {step.tool_name}"

            evaluated_plan_steps.append(
                {
                    "index": idx,
                    "step_id": step.step_id,
                    "tool_name": step.tool_name,
                    "tool": step.tool_name,
                    "command": str(cmd_val) if cmd_val else None,
                    "action": step_desc,
                    "description": step_desc,
                    "risk_level": effective_risk.value.upper(),
                    "mutative": is_step_mutative,
                    "read_only": not is_step_mutative,
                    "reversible": bool(tool.reversible if tool else step.reversible),
                }
            )

            if eval_res.decision == PolicyDecision.DENY:
                denied_reasons.append(
                    f"Acción denegada '{step.tool_name}': {eval_res.reason or 'Violación de seguridad'}"
                )

            if eval_res.decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL or effective_risk in (
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            ):
                requires_approval = True
                steps_requiring_approval.append(step.step_id)
                tool_name_entry = tool.name if tool else step.tool_name
                if tool_name_entry and tool_name_entry not in tools_requiring_approval:
                    tools_requiring_approval.append(tool_name_entry)
                approval_reasons.append(
                    f"Acción '{step.tool_name}' ({effective_risk.value.upper()}): {eval_res.reason}"
                )
                if eval_res.can_cause_data_loss or effective_risk == RiskLevel.CRITICAL:
                    has_data_loss = True

        # Resolver veredicto consolidado
        def _step_label(s: PlanStep) -> str:
            args = s.tool_args if isinstance(s.tool_args, dict) else {}
            cmd = (
                args.get("command")
                or args.get("target_url")
                or args.get("url")
                or args.get("target")
                or args.get("query")
            )
            return f"{s.tool_name} ('{cmd}')" if cmd else s.tool_name

        evaluated_labels = ", ".join(_step_label(s) for s in steps_to_evaluate)
        if denied_reasons:
            decision = PolicyDecision.DENY
            reason = " ; ".join(denied_reasons)
        elif requires_approval:
            decision = PolicyDecision.REQUIRE_HUMAN_APPROVAL
            reason = " ; ".join(approval_reasons)
        else:
            decision = PolicyDecision.ALLOW
            reason = (
                f"Operación [{evaluated_labels}] con nivel de riesgo operativo aceptable "
                f"({max_risk.value.upper()}) para ejecución autónoma."
            )

    # 4. Construir resultado formal de seguridad
    eval_result = SecurityEvaluationResult(
        decision=decision,
        operation="risk_assessment",
        target_resource="execution_plan" if plan else "tool_calls",
        risk_level=max_risk,
        reason=reason,
        can_cause_data_loss=has_data_loss,
    )

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # 5. Generar salto cognitivo para LangGraph
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
        description=(
            f"Evaluación completada con veredicto '{decision.value.upper()}' (Riesgo: {max_risk.value.upper()}). "
            f"{reason}"
        ),
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

    # 6. Generar mutaciones de estado para LangGraph
    risk_assessment_payload = eval_result.model_dump()
    mutative_count = sum(1 for s in evaluated_plan_steps if s.get("mutative"))
    risk_assessment_payload["plan_steps"] = evaluated_plan_steps
    risk_assessment_payload["mutative_steps_count"] = mutative_count
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

    # 7. Gestión del estado de aprobación humana (AWAITING_APPROVAL)
    if requires_approval:
        update_state["status"] = AgentExecutionStatus.AWAITING_APPROVAL
        update_state["approved_step_ids"] = steps_requiring_approval
        update_state["approved_tool_names"] = tools_requiring_approval

        # Preservar registro únicamente si ya estuviera aprobado previamente para estos mismos pasos
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
        # Si existen pasos aprobados específicos, exigir que las nuevas acciones mutativas estén dentro del conjunto aprobado
        if (
            is_already_approved
            and existing_approved_steps
            and steps_requiring_approval
            and not set(steps_requiring_approval).issubset(set(existing_approved_steps))
        ):
            is_already_approved = False

        if not is_already_approved:
            update_state["approval"] = ApprovalRecord(
                status=ApprovalStatus.PENDING,
                notes=reason,
                approved_step_ids=steps_requiring_approval,
                approved_tool_names=tools_requiring_approval,
            )
    elif decision == PolicyDecision.DENY:
        update_state["status"] = AgentExecutionStatus.FAILED

    return update_state
