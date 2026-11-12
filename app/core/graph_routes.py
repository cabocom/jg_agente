# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Enrutadores condicionales agnósticos para el flujo StateGraph de jg_agente."""

from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalStatus,
    GoalStatus,
    IntentModel,
    PolicyDecision,
    StepStatus,
    VerificationStatus,
)


def route_after_reason(
    state: AgentState,
    has_planner: bool,
    has_tools: bool,
    has_risk_assessment: bool = False,
) -> str:
    """Enruta desde 'reason' según la intención detectada y las capacidades disponibles."""
    intent = state.get("intent")
    action_type = ""
    if isinstance(intent, IntentModel):
        action_type = intent.action_type
    elif isinstance(intent, dict):
        action_type = intent.get("action_type", "")

    if action_type in ("conclude", "respond"):
        return "conclude"
    if has_planner:
        return "plan"
    if has_risk_assessment:
        return "risk_assess"
    if has_tools:
        return "execute"
    return "conclude"


def route_after_plan(state: AgentState, has_risk_assessment: bool) -> str:
    """Enruta desde 'plan' hacia evaluación de riesgo si existe, ejecución o conclude si falló."""
    plan = state.get("plan")
    has_steps = bool(plan and getattr(plan, "steps", None))
    has_fatal_error = any(getattr(e, "fatal", False) for e in (state.get("errors") or []))
    is_failed = (
        (not has_steps)
        or has_fatal_error
        or state.get("status") in (AgentExecutionStatus.FAILED, AgentExecutionStatus.FAILED.value)
    )

    if is_failed:
        return "conclude"

    if has_risk_assessment:
        return "risk_assess"
    return "execute"


def route_after_risk_assess(state: AgentState, has_human_approval: bool) -> str:
    """Enruta desde 'risk_assess' evaluando la política de seguridad."""
    risk_info = state.get("risk_assessment") or {}
    decision = (
        risk_info.get("decision")
        if isinstance(risk_info, dict)
        else getattr(risk_info, "decision", None)
    )

    if decision == PolicyDecision.DENY or decision == PolicyDecision.DENY.value:
        return "conclude"

    approval = state.get("approval")
    approval_status = (
        getattr(approval, "status", None)
        if approval
        else (approval.get("status") if isinstance(approval, dict) else None)
    )

    if (
        decision
        in (PolicyDecision.REQUIRE_HUMAN_APPROVAL, PolicyDecision.REQUIRE_HUMAN_APPROVAL.value)
        or approval_status == ApprovalStatus.PENDING
        or state.get("requires_approval") is True
        or state.get("human_intervention_required") is True
    ):
        if has_human_approval:
            return "human_approval"
        return "conclude"

    return "execute"


def route_after_human_approval(state: AgentState) -> str:
    """Enruta desde 'human_approval' tras evaluar el resultado de la autorización."""
    approval = state.get("approval")
    approval_status = (
        getattr(approval, "status", None)
        if approval
        else (approval.get("status") if isinstance(approval, dict) else None)
    )

    if approval_status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.AUTO_APPROVED.value,
    ):
        return "execute"
    return "conclude"


def route_after_execute(
    state: AgentState,
    has_verifier: bool,
    has_rollback: bool = False,
) -> str:
    """Enruta tras 'execute' hacia compensación, verificación o evaluación semántica."""
    if has_rollback and state.get("requires_rollback"):
        records = state.get("execution_records") or []
        if any(
            r.status == StepStatus.COMPLETED and r.rollback_context is not None for r in records
        ):
            return "rollback"
    if has_verifier:
        return "verify"
    return "evaluate"


def route_after_verify(
    state: AgentState,
    has_rollback: bool,
    has_evaluator: bool = True,
) -> str:
    """Enruta tras 'verify' evaluando si la comprobación fue exitosa o requiere compensación."""
    v_results = state.get("verification_results") or []
    has_failure = any(
        v.get("status") in (VerificationStatus.FAIL.value, VerificationStatus.DEGRADED.value)
        if isinstance(v, dict)
        else getattr(v, "status", None) in (VerificationStatus.FAIL, VerificationStatus.DEGRADED)
        for v in v_results
    )

    if has_failure and has_rollback:
        records = state.get("execution_records") or []
        has_reversible = any(
            r.status == StepStatus.COMPLETED and r.rollback_context is not None for r in records
        )
        if has_reversible:
            return "rollback"

    return "evaluate"


def route_after_evaluation(state: AgentState, has_rollback: bool = False) -> str:
    """Enruta tras 'evaluate' aplicando guardarraíles deterministas de iteración y estado del objetivo."""
    # 1. Guardarraíl de compensación si la evaluación o verificación detectó requerimiento explícito
    if state.get("requires_rollback") and has_rollback:
        return "rollback"

    # 2. Guardarraíl determinista de límite de iteraciones (previene bucles infinitos)
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 3)
    if iteration >= max_iterations:
        return "conclude"

    # 3. Inspección del último EvaluationRecord
    eval_records = state.get("evaluation_records") or []
    if not eval_records:
        return "conclude"

    last_eval = eval_records[-1]
    goal_status = getattr(last_eval, "goal_status", None)
    if isinstance(goal_status, GoalStatus):
        status_val = goal_status.value
    else:
        status_val = str(goal_status or "").lower().strip()

    if status_val in (
        GoalStatus.BLOCKED_MISSING_CAPABILITY.value,
        GoalStatus.SATISFIED.value,
        GoalStatus.FAILED.value,
        "blocked_missing_capability",
        "satisfied",
        "failed",
    ):
        return "conclude"

    if status_val in (GoalStatus.NEEDS_MORE_INFO.value, "needs_more_info"):
        return "reason"

    return "conclude"
