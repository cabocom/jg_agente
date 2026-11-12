# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo ejecutor de herramientas (execute) para jg_agente.

Ejecuta de forma secuencial las herramientas autorizadas, bien procedan de un plan
estructurado (ExecutionPlan) o de llamadas a herramientas emitidas por el LLM (tool_calls).
Interpola las directivas de seguridad a través de SecurityGuard, mide tiempos de ejecución,
captura fallos operacionales y preserva el contexto de compensación (rollback_context).
"""

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import ToolMessage

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
    ExecutionError,
    PlanStep,
    StepExecutionRecord,
    StepStatus,
)
from app.nodes.execute_approval_context import (
    resolve_execution_context,
    resolve_steps_to_run,
)
from app.nodes.execute_step_runner import run_single_step
from app.security.guard import SecurityGuard, get_security_guard

logger = logging.getLogger("jg_agente.nodes.execute")

__all__ = ["execute_node"]


def _handle_missing_tool(
    step: PlanStep,
) -> tuple[StepExecutionRecord, CognitiveStepRecord, ExecutionError]:
    """Genera registros y error cuando la herramienta no existe en el catálogo."""
    err_msg = f"La herramienta '{step.tool_name}' no existe en el CapabilityRegistry."
    logger.error("[execute_node] Error: %s", err_msg)
    allow_fail = bool(getattr(step, "allow_failure", False))
    err = ExecutionError(
        code="TOOL_NOT_FOUND", message=err_msg, component="execute", fatal=not allow_fail
    )
    step.status = StepStatus.FAILED
    record = StepExecutionRecord(
        step_id=step.step_id,
        tool_name=step.tool_name,
        tool_args=step.tool_args,
        status=StepStatus.FAILED,
        error=err_msg,
        duration_ms=0.0,
        timestamp=datetime.now(UTC),
    )
    cog_step = CognitiveStepRecord(
        step_id=f"cog_err_{step.step_id}",
        node="execute",
        title=f"Error en Herramienta: {step.tool_name}",
        action="Fallo de Localización",
        description=err_msg,
        status="failed",
        details={"tool_name": step.tool_name, "error": err_msg},
        duration_ms=0.0,
        timestamp=datetime.now(UTC),
    )
    return record, cog_step, err


def _build_mutations(
    state: AgentState,
    records: list[StepExecutionRecord],
    cognitive_steps: list[CognitiveStepRecord],
    errors: list[ExecutionError],
    tool_messages: list[ToolMessage],
    caller_perms: list[str],
    plan: Any,
) -> dict[str, Any]:
    """Consolida las mutaciones de estado para LangGraph tras la ejecución."""
    success_count = sum(1 for r in records if r.status == StepStatus.COMPLETED)
    failed_count = sum(1 for r in records if r.status == StepStatus.FAILED)
    has_fatal_failure = any(e.fatal for e in errors)
    all_session_records = list(state.get("execution_records") or []) + records
    has_compensable = any(
        r.status == StepStatus.COMPLETED and r.rollback_context is not None
        for r in all_session_records
    )

    mutations: dict[str, Any] = {
        "status": AgentExecutionStatus.EXECUTING,
        "requires_rollback": bool(has_fatal_failure and has_compensable),
        "caller_permissions": caller_perms,
        "execution_records": records,
        "cognitive_steps": cognitive_steps,
        "errors": errors,
        "audit_trail": [
            AuditRecord(
                event_type="execute_completed",
                actor="execute_node",
                details={
                    "steps_executed": len(records),
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "tools": [r.tool_name for r in records],
                },
                timestamp=datetime.now(UTC),
            )
        ],
    }
    if tool_messages:
        mutations["messages"] = tool_messages
    if plan is not None:
        mutations["plan"] = plan
    return mutations


async def execute_node(
    state: AgentState,
    registry: CapabilityRegistry,
    security_guard: SecurityGuard | None = None,
) -> dict[str, Any]:
    """Ejecuta secuencialmente herramientas autorizadas bajo sandbox y gobernanza HITL."""
    guard = security_guard or get_security_guard()
    exec_id, thread_id, is_plan_approved, approved_step_ids, approved_tool_names, caller_perms = (
        resolve_execution_context(state)
    )
    plan, steps_to_run = resolve_steps_to_run(state, registry)

    records: list[StepExecutionRecord] = []
    cognitive_steps: list[CognitiveStepRecord] = []
    errors: list[ExecutionError] = []
    tool_messages: list[ToolMessage] = []

    for step in steps_to_run:
        tool = registry.get_tool(step.tool_name)
        if not tool:
            rec, cog, err = _handle_missing_tool(step)
            records.append(rec)
            cognitive_steps.append(cog)
            errors.append(err)
            if err.fatal:
                break
            continue

        step.status = StepStatus.RUNNING
        logger.info(
            "[execute_node] Ejecutando paso '%s' con herramienta '%s'", step.step_id, tool.name
        )

        step_bypass = False
        if is_plan_approved:
            step_bypass = (
                not (approved_step_ids or approved_tool_names)
                or step.step_id in approved_step_ids
                or step.tool_name in approved_tool_names
            )

        rec, sec_c, exec_c, t_msg, err_or_none = await run_single_step(
            step=step,
            tool=tool,
            guard=guard,
            step_bypass_approval=step_bypass,
            caller_perms=caller_perms,
            execution_id=exec_id,
            thread_id=thread_id,
            approved_step_ids=approved_step_ids,
            approved_tool_names=approved_tool_names,
            checkpoint_degraded=bool(state.get("checkpoint_degraded", False)),
        )

        records.append(rec)
        cognitive_steps.extend([sec_c, exec_c])
        tool_messages.append(t_msg)

        if err_or_none is not None:
            errors.append(err_or_none)
            if err_or_none.fatal:
                logger.info(
                    "[execute_node] Paso '%s' es crítico. Abortando pasos restantes.", step.step_id
                )
                break

    return _build_mutations(
        state, records, cognitive_steps, errors, tool_messages, caller_perms, plan
    )
