"""Nodo de evaluación de riesgo y política HITL (risk_assess) para jg_agente.

Analiza las acciones previstas en el plan estructurado (ExecutionPlan) o las llamadas
a herramientas (tool_calls), evaluando permisos, directivas de red e inyecciones
mediante SecurityGuard. Si alguna acción presenta RiskLevel >= HIGH, marca requires_approval=True
y deriva la ejecución hacia la puerta de aprobación humana (human_approval).
"""

import logging
import time
from typing import Any

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    AuditRecord,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    PolicyDecision,
    SecurityEvaluationResult,
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

        for idx, tc in enumerate(tcs):
            tc_name = tc.get("name") or tc.get("tool_name", f"tool-{idx}")
            tc_args = tc.get("args") or tc.get("tool_args", {})
            steps_to_evaluate.append(
                PlanStep(
                    step_id=f"tool-call-{idx}",
                    tool_name=tc_name,
                    tool_args=tc_args,
                    risk_level=RiskLevel.LOW,
                )
            )

    # 3. Evaluar cada acción mediante SecurityGuard
    max_risk = RiskLevel.LOW
    requires_approval = False
    has_data_loss = False
    denied_reasons: list[str] = []
    approval_reasons: list[str] = []

    if not steps_to_evaluate:
        decision = PolicyDecision.ALLOW
        reason = "No se detectaron operaciones que requieran evaluación de riesgo."
    else:
        for step in steps_to_evaluate:
            tool = registry.get_tool(step.tool_name) if registry else None
            effective_risk = tool.risk_level if tool else step.risk_level

            # Actualizar máximo riesgo observado
            if _RISK_ORDER.get(effective_risk, 1) > _RISK_ORDER.get(max_risk, 1):
                max_risk = effective_risk

            caller_perms = (
                list(req.user_context.permissions)
                if req and req.user_context and req.user_context.permissions
                else (list(tool.required_permissions) if tool else [])
            )

            # Evaluar con SecurityGuard
            eval_res = guard.evaluate(
                tool=tool or step.tool_name,
                tool_args=step.tool_args,
                risk_level=effective_risk,
                caller_permissions=caller_perms,
                is_reversible=tool.reversible if tool else step.reversible,
                execution_id=execution_id,
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
                approval_reasons.append(
                    f"Acción '{step.tool_name}' ({effective_risk.value.upper()}): {eval_res.reason}"
                )
                if eval_res.can_cause_data_loss or effective_risk == RiskLevel.CRITICAL:
                    has_data_loss = True

        # Resolver veredicto consolidado
        if denied_reasons:
            decision = PolicyDecision.DENY
            reason = " ; ".join(denied_reasons)
        elif requires_approval:
            decision = PolicyDecision.REQUIRE_HUMAN_APPROVAL
            reason = " ; ".join(approval_reasons)
        else:
            decision = PolicyDecision.ALLOW
            reason = "Operaciones con nivel de riesgo operativo aceptable para ejecución autónoma."

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

    # 5. Generar mutaciones de estado para LangGraph
    update_state: dict[str, Any] = {
        "risk_assessment": eval_result.model_dump(),
        "requires_approval": requires_approval,
        "human_intervention_required": requires_approval,
        "circuit_breaker_active": decision == PolicyDecision.DENY,
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

    # 6. Gestión del estado de aprobación humana (AWAITING_APPROVAL)
    if requires_approval:
        update_state["status"] = AgentExecutionStatus.AWAITING_APPROVAL

        # Preservar registro si ya estuviera aprobado previamente (reanudación HITL)
        current_approval = state.get("approval")
        current_status = None
        if isinstance(current_approval, ApprovalRecord):
            current_status = current_approval.status
        elif isinstance(current_approval, dict):
            current_status = current_approval.get("status")

        if current_status not in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.APPROVED.value,
            ApprovalStatus.AUTO_APPROVED,
            ApprovalStatus.AUTO_APPROVED.value,
        ):
            update_state["approval"] = ApprovalRecord(
                status=ApprovalStatus.PENDING,
                notes=reason,
            )
    elif decision == PolicyDecision.DENY:
        update_state["status"] = AgentExecutionStatus.FAILED

    return update_state
