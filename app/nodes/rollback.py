# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo de compensación (rollback) para jg_agente.

Revierte los efectos colaterales de herramientas reversibles ejecutadas (en orden cronológico
inverso) cuando el nodo verify detecta anomalías o fallos operacionales en el sistema.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.async_compat import ensure_awaited
from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
    ExecutionError,
    StepStatus,
)

logger = logging.getLogger("jg_agente.nodes.rollback")


async def rollback_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Ejecuta la compensación secuencial en orden inverso para pasos reversibles completados.

    Args:
        state: Estado global actual del agente (AgentState).
        registry: Catálogo de capacidades registrado opcional.

    Returns:
        Mutaciones del estado para LangGraph (status, rollback_records, errors, audit_trail).
    """
    start_time = time.perf_counter()

    records = list(state.get("execution_records") or [])
    rollback_traces: list[dict[str, Any]] = []
    cog_steps: list[CognitiveStepRecord] = []

    # 1. Revertir en orden cronológico inverso (LIFO) los pasos completados
    lifo_idx = 0
    for rec in reversed(records):
        if rec.status == StepStatus.COMPLETED and rec.rollback_context is not None:
            tool = registry.get_tool(rec.tool_name) if registry else None
            if tool is not None and tool.reversible:
                lifo_idx += 1
                rb_ctx = rec.rollback_context if isinstance(rec.rollback_context, dict) else {}
                comp_cmd = (
                    rb_ctx.get("command")
                    or rb_ctx.get("compensatory_command")
                    or rb_ctx.get("description")
                    or f"rollback({rec.tool_name})"
                )
                orig_cmd = (
                    rb_ctx.get("original_command")
                    or (rec.tool_args.get("command") if isinstance(rec.tool_args, dict) else None)
                    or rec.tool_name
                )
                logger.warning(
                    "[rollback_node] Compensando paso LIFO #%d '%s' con herramienta '%s' (%s)...",
                    lifo_idx,
                    rec.step_id,
                    rec.tool_name,
                    comp_cmd,
                )
                try:
                    res = tool.rollback(rec.rollback_context)
                    tool_res = await ensure_awaited(res)
                    step_dur = float(getattr(tool_res, "duration_ms", 0.0) or 0.0)
                    trace_item = {
                        "lifo_order": lifo_idx,
                        "step_id": rec.step_id,
                        "tool_name": rec.tool_name,
                        "original_command": orig_cmd,
                        "compensatory_command": comp_cmd,
                        "success": tool_res.success,
                        "output": tool_res.output,
                        "error": tool_res.error,
                        "duration_ms": step_dur,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    rollback_traces.append(trace_item)
                    cog_steps.append(
                        CognitiveStepRecord(
                            step_id=f"cog_rollback_step_{lifo_idx}_{rec.step_id}",
                            node="rollback",
                            title=f"Compensación Saga [LIFO #{lifo_idx}]: {comp_cmd}",
                            action=f"Revertir '{orig_cmd}' → '{comp_cmd}'",
                            description=(
                                f"Paso compensatorio #{lifo_idx} (LIFO) para revertir '{orig_cmd}': "
                                f"{tool_res.output if tool_res.success else (tool_res.error or 'Fallo en compensación')}"
                            ),
                            status="completed" if tool_res.success else "failed",
                            details=trace_item,
                            duration_ms=step_dur,
                            timestamp=datetime.now(UTC),
                        )
                    )
                except Exception as exc:
                    logger.exception(
                        "[rollback_node] Excepción durante compensación de '%s': %s",
                        rec.tool_name,
                        exc,
                    )
                    trace_item = {
                        "lifo_order": lifo_idx,
                        "step_id": rec.step_id,
                        "tool_name": rec.tool_name,
                        "original_command": orig_cmd,
                        "compensatory_command": comp_cmd,
                        "success": False,
                        "output": "",
                        "error": f"Excepción durante rollback: {exc}",
                        "duration_ms": 0.0,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    rollback_traces.append(trace_item)
                    cog_steps.append(
                        CognitiveStepRecord(
                            step_id=f"cog_rollback_step_{lifo_idx}_{rec.step_id}",
                            node="rollback",
                            title=f"Compensación Saga [LIFO #{lifo_idx}]: {comp_cmd}",
                            action=f"Fallo al revertir '{orig_cmd}'",
                            description=f"Excepción ejecutando compensador '{comp_cmd}': {exc}",
                            status="failed",
                            details=trace_item,
                            duration_ms=0.0,
                            timestamp=datetime.now(UTC),
                        )
                    )
            elif tool is not None and not tool.reversible:
                logger.info(
                    "[rollback_node] Paso '%s' (%s) omitido de compensación: no es reversible.",
                    rec.step_id,
                    rec.tool_name,
                )

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    succeeded_count = sum(1 for t in rollback_traces if t.get("success", False))
    failed_count = len(rollback_traces) - succeeded_count

    # 2. Emisión de traza de auditoría inmutable
    audit = AuditRecord(
        event_type="rollback_completed",
        actor="rollback_node",
        details={
            "steps_reverted": len(rollback_traces),
            "succeeded": succeeded_count,
            "failed": failed_count,
            "duration_ms": duration_ms,
        },
    )

    # 3. Registrar error fatal para señalizar el fallo global que activó la compensación
    err_msg = (
        f"Se ejecutó compensación automática (rollback) de {len(rollback_traces)} pasos reversibles "
        f"({succeeded_count} exitosos, {failed_count} fallidos)."
    )
    rollback_error = ExecutionError(
        code="ROLLBACK_TRIGGERED",
        message=err_msg,
        component="rollback",
        fatal=True,
    )

    cog_rollback = CognitiveStepRecord(
        step_id=f"cog_rollback_{int(time.time() * 1000)}",
        node="rollback",
        title="Compensación Automática (Rollback Saga LIFO)",
        action=f"Reversión de {len(rollback_traces)} operaciones",
        description=(
            f"Se ejecutó compensación automática en orden inverso (LIFO) de {len(rollback_traces)} pasos reversibles "
            f"({succeeded_count} revertidos exitosamente, {failed_count} fallidos)."
        ),
        status="completed" if failed_count == 0 else "failed",
        details={
            "steps_reverted": len(rollback_traces),
            "succeeded": succeeded_count,
            "failed": failed_count,
            "traces": rollback_traces,
        },
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )
    cog_steps.append(cog_rollback)

    return {
        "status": AgentExecutionStatus.FAILED,
        "rollback_records": rollback_traces,
        "cognitive_steps": cog_steps,
        "errors": [rollback_error],
        "audit_trail": [audit],
    }
