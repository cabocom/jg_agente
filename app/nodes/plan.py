# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo de planificación DAG (plan_node) para el motor cognitivo de jg_agente."""

import inspect
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.async_compat import is_awaitable_or_coroutine
from app.core.registry import CapabilityRegistry
from app.models.records import (
    AuditRecord,
    CognitiveStepRecord,
    ExecutionError,
    ExecutionPlan,
    IntentModel,
    PlanStep,
)
from app.models.state import AgentExecutionStatus, AgentState
from app.models.tools import RiskLevel
from app.plugins.base import BaseEngine, PlannerEngine

logger = logging.getLogger("jg_agente.nodes.plan")

_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


def _compute_highest_risk(steps: list[PlanStep]) -> RiskLevel:
    """Determina el nivel de riesgo más restrictivo a partir de los pasos de un plan."""
    if not steps:
        return RiskLevel.LOW
    highest = max(steps, key=lambda s: _RISK_ORDER.get(s.risk_level, 1))
    return highest.risk_level


def _convert_raw_steps(raw_plan: list[Any], state: AgentState) -> ExecutionPlan:
    """Convierte una lista de pasos crudos en una instancia formal de ExecutionPlan."""
    raw_steps: list[PlanStep] = []
    for item in raw_plan:
        if isinstance(item, PlanStep):
            raw_steps.append(item)
        elif isinstance(item, dict):
            raw_steps.append(PlanStep(**item))
    intent_val = state.get("intent")
    goal_val = (
        intent_val.goal if isinstance(intent_val, IntentModel) else "Plan de ejecución estructurado"
    )
    return ExecutionPlan(
        plan_id=f"plan-{int(datetime.now(UTC).timestamp())}",
        goal=goal_val,
        steps=raw_steps,
        estimated_risk=_compute_highest_risk(raw_steps),
    )


async def _invoke_planner_engine(
    planner: PlannerEngine | BaseEngine | None,
    state: AgentState,
) -> tuple[ExecutionPlan | None, list[ExecutionError]]:
    """Invoca polimórficamente el motor de planificación si está registrado."""
    if planner is None:
        return None, []
    plan_fn = None
    for candidate in ("create_plan", "plan", "build_plan", "generate_plan"):
        attr = getattr(planner, candidate, None)
        if callable(attr):
            plan_fn = attr
            break
    if plan_fn is None:
        return None, []
    try:
        sig = inspect.signature(plan_fn)
        call_with_state = len(sig.parameters) > 0
    except (TypeError, ValueError):
        call_with_state = True

    try:
        res = plan_fn(state) if call_with_state else plan_fn()
        raw = await res if is_awaitable_or_coroutine(res) else res
        if isinstance(raw, ExecutionPlan):
            return raw, []
        if isinstance(raw, dict):
            return ExecutionPlan(**raw), []
        if isinstance(raw, list):
            return _convert_raw_steps(raw, state), []
        return None, []
    except Exception as err:
        logger.exception("Excepción en el motor de planificación %s", planner.name)
        return None, [
            ExecutionError(
                code="PLANNER_EXECUTION_ERROR",
                message=f"Fallo durante la planificación en el motor '{planner.name}': {err}",
                component="plan",
                fatal=False,
            )
        ]


def _extract_steps_from_tool_calls(
    intent: Any,
    registry: CapabilityRegistry | None,
) -> tuple[list[PlanStep], list[ExecutionError]]:
    """Extrae PlanSteps a partir de tool_calls emitidas en el paso de razonamiento previo."""
    tcs: list[dict[str, Any]] = []
    if isinstance(intent, IntentModel) and intent.parameters:
        tcs = intent.parameters.get("tool_calls", [])
    elif isinstance(intent, dict):
        tcs = intent.get("parameters", {}).get("tool_calls", [])

    if not tcs:
        logger.warning(
            "[plan_node] No se generó un plan estructurado válido ni existen tool_calls previas."
        )
        return [], [
            ExecutionError(
                code="PLANNING_FAILED",
                message="No fue posible generar un plan estructurado válido para la solicitud.",
                component="plan",
                fatal=True,
            )
        ]
    steps: list[PlanStep] = []
    for idx, tc in enumerate(tcs, start=1):
        name = tc.get("name") or tc.get("tool_name", f"tool-{idx}")
        args = tc.get("args") or tc.get("tool_args", {})
        t_def = registry.get_tool(name) if registry else None
        steps.append(
            PlanStep(
                step_id=f"step-{idx}",
                tool_name=name,
                tool_args=args if isinstance(args, dict) else {},
                description=f"Ejecutar {name}",
                risk_level=t_def.risk_level if t_def else RiskLevel.LOW,
                reversible=t_def.reversible if t_def else False,
                allow_failure=getattr(t_def, "allow_failure", False)
                if t_def
                else bool(tc.get("allow_failure", False)),
                dependencies=[f"step-{idx - 1}"] if idx > 1 else [],
            )
        )
    return steps, []


def _build_fallback_plan(
    state: AgentState,
    registry: CapabilityRegistry | None,
) -> tuple[ExecutionPlan, list[ExecutionError]]:
    """Construye un plan operativo seguro de contingencia a partir del intent del estado."""
    intent = state.get("intent")
    goal = (
        intent.goal
        if isinstance(intent, IntentModel)
        else getattr(state.get("request"), "prompt", "Ejecución de plan estándar")
    )
    steps, errors = _extract_steps_from_tool_calls(intent, registry)
    plan = ExecutionPlan(
        plan_id=f"plan-{int(datetime.now(UTC).timestamp())}",
        goal=goal,
        steps=steps,
        estimated_risk=_compute_highest_risk(steps) if steps else RiskLevel.LOW,
    )
    return plan, errors


def _build_plan_audit_records(
    plan: ExecutionPlan,
    planner: Any,
    errors: list[ExecutionError],
    is_failed: bool,
    duration_ms: float,
) -> tuple[AuditRecord, CognitiveStepRecord]:
    """Formula los registros estructurados de auditoría y salto cognitivo."""
    audit = AuditRecord(
        event_type="planning_completed",
        actor=planner.name if planner else "core",
        details={
            "plan_id": plan.plan_id,
            "steps_count": len(plan.steps),
            "estimated_risk": plan.estimated_risk.value,
            "duration_ms": duration_ms,
            "has_errors": len(errors) > 0,
            "is_failed": is_failed,
        },
    )
    action_str = (
        "Fallo de Planificación"
        if is_failed
        else f"Descomposición de Tarea ({len(plan.steps)} pasos)"
    )
    desc_str = (
        "No fue posible generar un plan estructurado válido para la solicitud."
        if is_failed
        else f"Se elaboró un plan con objetivo '{plan.goal}' y riesgo '{plan.estimated_risk.value.upper()}'."
    )
    cog = CognitiveStepRecord(
        step_id=f"cog_plan_{int(time.time() * 1000)}",
        node="plan",
        title="Planificación Estratégica (DAG Planner)"
        if planner
        else "Generación de Plan Operativo",
        action=action_str,
        description=desc_str,
        status="failed" if is_failed else "completed",
        details={
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "steps_count": len(plan.steps),
            "estimated_risk": plan.estimated_risk.value,
            "steps": [
                s.model_dump(mode="json") if hasattr(s, "model_dump") else s for s in plan.steps
            ],
            "failure_reason": errors[-1].message if is_failed and errors else None,
        },
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )
    return audit, cog


async def plan_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
    engine: PlannerEngine | BaseEngine | None = None,
) -> dict[str, Any]:
    """Genera una secuencia estructurada de pasos (ExecutionPlan) a partir de la intención del agente."""
    start_time = time.perf_counter()
    planner = engine or (registry.get_planner() if registry else None)
    plan, errors = await _invoke_planner_engine(planner, state)
    if plan is None:
        plan, fb_errors = _build_fallback_plan(state, registry)
        errors.extend(fb_errors)
    elif plan.steps and plan.estimated_risk == RiskLevel.LOW:
        calc_risk = _compute_highest_risk(plan.steps)
        if calc_risk != plan.estimated_risk:
            plan.estimated_risk = calc_risk

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    is_failed = (not plan.steps) or any(getattr(e, "fatal", False) for e in errors)
    audit, cog = _build_plan_audit_records(plan, planner, errors, is_failed, duration_ms)

    updates: dict[str, Any] = {
        "status": AgentExecutionStatus.FAILED if is_failed else AgentExecutionStatus.PLANNING,
        "plan": plan,
        "cognitive_steps": [cog],
        "audit_trail": [audit],
    }
    if errors:
        updates["errors"] = errors
    return updates
