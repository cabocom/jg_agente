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

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
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
            raw_plan = await res if inspect.iscoroutine(res) else res

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
                steps.append(
                    PlanStep(
                        step_id=f"step-{idx}",
                        tool_name=tc_name,
                        tool_args=tc_args if isinstance(tc_args, dict) else {},
                        description=f"Ejecutar {tc_name}",
                        risk_level=t_risk,
                        reversible=t_rev,
                        dependencies=[f"step-{idx-1}"] if idx > 1 else [],
                    )
                )
        elif registry is not None:
            available_tools = registry.list_tools()
            if available_tools:
                target_tool = available_tools[0]
                steps.append(
                    PlanStep(
                        step_id="step-1",
                        tool_name=target_tool.name,
                        tool_args={},
                        description=f"Ejecutar {target_tool.name}",
                        risk_level=target_tool.risk_level,
                        reversible=target_tool.reversible,
                        dependencies=[],
                    )
                )

        plan = ExecutionPlan(
            plan_id=f"plan-{int(datetime.now(UTC).timestamp())}",
            goal=goal,
            steps=steps,
            estimated_risk=_compute_highest_risk(steps),
        )
    else:
        # Asegurar consistencia del riesgo estimado consolidado
        if plan.steps and plan.estimated_risk == RiskLevel.LOW:
            calculated_risk = _compute_highest_risk(plan.steps)
            if calculated_risk != plan.estimated_risk:
                plan.estimated_risk = calculated_risk

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

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
        },
    )

    updates: dict[str, Any] = {
        "status": AgentExecutionStatus.PLANNING,
        "plan": plan,
        "audit_trail": [audit],
    }
    if errors:
        updates["errors"] = errors

    return updates
