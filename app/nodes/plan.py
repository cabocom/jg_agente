# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo opcional de planificación (plan) para jg_agente.

Se activa condicionalmente si existe un PlannerEngine registrado en CapabilityRegistry.
Transforma el estímulo cognitivo y el IntentModel en un ExecutionPlan estructurado
con pasos ordenados (PlanStep), dependencias secuenciales y evaluación de riesgo.
"""

import inspect
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.async_compat import is_awaitable_or_coroutine
from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
    ExecutionError,
    ExecutionPlan,
    IntentModel,
    PlanStep,
)
from app.models.tools import RiskLevel
from app.plugins.base import BaseEngine, PlannerEngine

logger = logging.getLogger("jg_agente.nodes.plan")

_RISK_ORDER: dict[RiskLevel | str, int] = {
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


async def plan_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
    engine: PlannerEngine | BaseEngine | None = None,
) -> dict[str, Any]:
    """Genera una secuencia estructurada de pasos (ExecutionPlan) a partir de la intención del agente.

    Args:
        state: Estado global actual del agente (AgentState).
        registry: Catálogo de capacidades registrado opcional.
        engine: Instancia directa de PlannerEngine (prioritaria sobre el catálogo).

    Returns:
        Mutaciones del estado para LangGraph (status, plan, audit_trail y opcionalmente errors).
    """
    start_time = time.perf_counter()
    errors: list[ExecutionError] = []

    # 1. Resolver el motor de planificación
    planner = engine
    if planner is None and registry is not None:
        planner = registry.get_planner()

    plan: ExecutionPlan | None = None

    # 2. Localizar el método invocable del motor (create_plan, plan, build_plan, generate_plan)
    plan_fn = None
    if planner is not None:
        for candidate in ("create_plan", "plan", "build_plan", "generate_plan"):
            attr = getattr(planner, candidate, None)
            if callable(attr):
                plan_fn = attr
                break

    # 3. Invocar el motor de planificación polimórficamente
    if planner is not None and plan_fn is not None:
        try:
            call_with_state = True
            try:
                sig = inspect.signature(plan_fn)
                call_with_state = len(sig.parameters) > 0
            except (TypeError, ValueError):
                call_with_state = True

            res = plan_fn(state) if call_with_state else plan_fn()
            raw_plan = await res if is_awaitable_or_coroutine(res) else res

            if isinstance(raw_plan, ExecutionPlan):
                plan = raw_plan
            elif isinstance(raw_plan, dict):
                plan = ExecutionPlan(**raw_plan)
            elif isinstance(raw_plan, list):
                raw_steps: list[PlanStep] = []
                for item in raw_plan:
                    if isinstance(item, PlanStep):
                        raw_steps.append(item)
                    elif isinstance(item, dict):
                        raw_steps.append(PlanStep(**item))
                intent_val = state.get("intent")
                goal_val = (
                    intent_val.goal
                    if isinstance(intent_val, IntentModel)
                    else "Plan de ejecución estructurado"
                )
                plan = ExecutionPlan(
                    plan_id=f"plan-{int(datetime.now(UTC).timestamp())}",
                    goal=goal_val,
                    steps=raw_steps,
                    estimated_risk=_compute_highest_risk(raw_steps),
                )
        except Exception as err:
            logger.exception("Excepción en el motor de planificación %s", planner.name)
            errors.append(
                ExecutionError(
                    code="PLANNER_EXECUTION_ERROR",
                    message=f"Fallo durante la planificación en el motor '{planner.name}': {err}",
                    component="plan",
                    fatal=False,
                )
            )
            plan = None

    # 4. Plan de contingencia o fallback seguro si no hay motor o falló
    if plan is None:
        intent = state.get("intent")
        goal = (
            intent.goal
            if isinstance(intent, IntentModel)
            else getattr(state.get("request"), "prompt", "Ejecución de plan estándar")
        )
        steps: list[PlanStep] = []

        # Extraer tool_calls si fueron emitidas en reason_node
        tcs: list[dict[str, Any]] = []
        if isinstance(intent, IntentModel) and intent.parameters:
            tcs = intent.parameters.get("tool_calls", [])
        elif isinstance(intent, dict):
            tcs = intent.get("parameters", {}).get("tool_calls", [])

        if tcs:
            for idx, tc in enumerate(tcs, start=1):
                tc_name = tc.get("name") or tc.get("tool_name", f"tool-{idx}")
                tc_args = tc.get("args") or tc.get("tool_args", {})
                tool_def = registry.get_tool(tc_name) if registry else None
                t_risk = tool_def.risk_level if tool_def else RiskLevel.LOW
                t_rev = tool_def.reversible if tool_def else False
                t_allow_failure = (
                    getattr(tool_def, "allow_failure", False)
                    if tool_def
                    else bool(tc.get("allow_failure", False))
                )
                steps.append(
                    PlanStep(
                        step_id=f"step-{idx}",
                        tool_name=tc_name,
                        tool_args=tc_args if isinstance(tc_args, dict) else {},
                        description=f"Ejecutar {tc_name}",
                        risk_level=t_risk,
                        reversible=t_rev,
                        allow_failure=t_allow_failure,
                        dependencies=[f"step-{idx - 1}"] if idx > 1 else [],
                    )
                )
        else:
            # AGENTE-LOGIC-02: Nunca ejecutar una herramienta arbitraria (available_tools[0]) con {} por defecto.
            logger.warning(
                "[plan_node] No se generó un plan estructurado válido ni existen tool_calls previas. Abortando fallback ciego."
            )
            errors.append(
                ExecutionError(
                    code="PLANNING_FAILED",
                    message="No fue posible generar un plan estructurado válido para la solicitud.",
                    component="plan",
                    fatal=True,
                )
            )

        plan = ExecutionPlan(
            plan_id=f"plan-{int(datetime.now(UTC).timestamp())}",
            goal=goal,
            steps=steps,
            estimated_risk=_compute_highest_risk(steps) if steps else RiskLevel.LOW,
        )
    else:
        # Asegurar consistencia del riesgo estimado consolidado
        if plan.steps and plan.estimated_risk == RiskLevel.LOW:
            calculated_risk = _compute_highest_risk(plan.steps)
            if calculated_risk != plan.estimated_risk:
                plan.estimated_risk = calculated_risk

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    has_steps = bool(plan.steps)
    has_fatal_error = any(getattr(e, "fatal", False) for e in errors)
    is_failed = (not has_steps) or has_fatal_error

    # 5. Emitir traza inmutable de auditoría
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

    cognitive_step = CognitiveStepRecord(
        step_id=f"cog_plan_{int(time.time() * 1000)}",
        node="plan",
        title="Planificación Estratégica (DAG Planner)"
        if planner
        else "Generación de Plan Operativo",
        action="Fallo de Planificación"
        if is_failed
        else f"Descomposición de Tarea ({len(plan.steps)} pasos)",
        description=(
            "No fue posible generar un plan estructurado válido para la solicitud. Se aborta la ejecución de herramientas por defecto."
            if is_failed
            else f"Se elaboró un plan con objetivo '{plan.goal}' y nivel de riesgo estimado '{plan.estimated_risk.value.upper()}'."
        ),
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

    updates: dict[str, Any] = {
        "status": AgentExecutionStatus.FAILED if is_failed else AgentExecutionStatus.PLANNING,
        "plan": plan,
        "cognitive_steps": [cognitive_step],
        "audit_trail": [audit],
    }
    if errors:
        updates["errors"] = errors

    return updates
