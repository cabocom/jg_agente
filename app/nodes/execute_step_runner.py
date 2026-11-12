# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Ejecución de un paso individual bajo gobernanza y sandbox de SecurityGuard."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import ToolMessage

from app.core.async_compat import is_awaitable_or_coroutine
from app.models.state import (
    CognitiveStepRecord,
    ExecutionError,
    PlanStep,
    StepExecutionRecord,
    StepStatus,
)
from app.models.tools import ToolResult
from app.security.guard import SecurityGuard

logger = logging.getLogger("jg_agente.nodes.execute_step_runner")


def _format_op_label(tool_name: str, tool_args: Any) -> tuple[str, str]:
    """Genera etiqueta y resumen de argumentos para visualización cognitiva."""
    arg_summary = ""
    if isinstance(tool_args, dict):
        arg_summary = str(
            tool_args.get("command")
            or tool_args.get("target_url")
            or tool_args.get("url")
            or tool_args.get("target")
            or tool_args.get("query")
            or ""
        ).strip()
    op_label = f"{tool_name} ('{arg_summary}')" if arg_summary else tool_name
    return op_label, arg_summary


def create_security_eval_step(
    step: PlanStep,
    tool: Any,
    step_bypass_approval: bool,
    op_label: str,
    arg_summary: str,
) -> CognitiveStepRecord:
    """Crea el registro cognitivo de evaluación de políticas previas a la ejecución."""
    sec_desc = (
        f"Operación '{op_label}' evaluada con riesgo {tool.risk_level.value.upper()}. "
        f"{'Autorizada previamente vía HITL.' if step_bypass_approval else 'Política: Ejecución autónoma autorizada (ALLOW).'}"
    )
    return CognitiveStepRecord(
        step_id=f"cog_sec_{step.step_id}",
        node="security_eval",
        title="Evaluación de Seguridad y Gobernanza (SecurityGuard)",
        action=f"Auditoría de Políticas: {op_label}",
        description=sec_desc,
        status="completed",
        details={
            "tool": tool.name,
            "command": arg_summary or None,
            "risk_level": tool.risk_level.value,
            "decision": "allow",
            "bypass_approval": step_bypass_approval,
            "reversible": tool.reversible,
        },
        duration_ms=0.0,
        timestamp=datetime.now(UTC),
    )


async def execute_tool_with_guard(
    tool: Any,
    step: PlanStep,
    guard: SecurityGuard,
    caller_perms: list[str],
    step_bypass_approval: bool,
    execution_id: str | None,
    thread_id: str | None,
    approved_step_ids: set[str],
    approved_tool_names: set[str],
    checkpoint_degraded: bool,
) -> ToolResult:
    """Invoca la herramienta a través de SecurityGuard gestionando timeouts."""
    timeout_sec = getattr(tool, "timeout_sec", 30.0) or 30.0
    try:
        tool_result = await asyncio.wait_for(
            guard.execute_tool(
                tool=tool,
                tool_args=step.tool_args,
                caller_permissions=caller_perms,
                bypass_approval=step_bypass_approval,
                execution_id=execution_id,
                thread_id=thread_id,
                step_id=step.step_id,
                approved_step_ids=list(approved_step_ids) if approved_step_ids else None,
                approved_tool_names=list(approved_tool_names) if approved_tool_names else None,
                checkpoint_degraded=checkpoint_degraded,
            ),
            timeout=timeout_sec,
        )
    except TimeoutError:
        err_desc = (
            f"TimeoutError: La ejecución del paso '{step.step_id}' con herramienta "
            f"'{tool.name}' superó el límite de {timeout_sec}s."
        )
        logger.warning("[execute_step_runner] %s", err_desc)
        tool_result = ToolResult(
            success=False,
            error=err_desc,
            duration_ms=timeout_sec * 1000.0,
            metadata={"timeout_sec": timeout_sec, "timed_out": True},
        )

    # Soporte para herramientas que devuelven corrutinas (retrocompatibilidad)
    if is_awaitable_or_coroutine(tool_result.output):
        try:
            tool_result.output = await asyncio.wait_for(tool_result.output, timeout=timeout_sec)
        except TimeoutError:
            err_desc = f"TimeoutError: La corrutina de salida de '{tool.name}' superó el límite de {timeout_sec}s."
            logger.warning("[execute_step_runner] %s", err_desc)
            tool_result = ToolResult(
                success=False,
                error=err_desc,
                duration_ms=timeout_sec * 1000.0,
                metadata={"timeout_sec": timeout_sec, "timed_out": True},
            )

    return tool_result


async def run_single_step(
    step: PlanStep,
    tool: Any,
    guard: SecurityGuard,
    step_bypass_approval: bool,
    caller_perms: list[str],
    execution_id: str | None,
    thread_id: str | None,
    approved_step_ids: set[str],
    approved_tool_names: set[str],
    checkpoint_degraded: bool,
) -> tuple[
    StepExecutionRecord,
    CognitiveStepRecord,
    CognitiveStepRecord,
    ToolMessage,
    ExecutionError | None,
]:
    """Ejecuta un paso individual retornando los artefactos de ejecución y auditoría correspondientes."""
    op_label, arg_summary = _format_op_label(tool.name, step.tool_args)
    sec_step = create_security_eval_step(step, tool, step_bypass_approval, op_label, arg_summary)

    tool_result = await execute_tool_with_guard(
        tool=tool,
        step=step,
        guard=guard,
        caller_perms=caller_perms,
        step_bypass_approval=step_bypass_approval,
        execution_id=execution_id,
        thread_id=thread_id,
        approved_step_ids=approved_step_ids,
        approved_tool_names=approved_tool_names,
        checkpoint_degraded=checkpoint_degraded,
    )

    final_output = tool_result.output
    if is_awaitable_or_coroutine(final_output):
        try:
            final_output = await final_output
        except Exception as e:
            final_output = f"<coroutine unresolved: {e}>"

    step_status = StepStatus.COMPLETED if tool_result.success else StepStatus.FAILED
    step.status = step_status

    record = StepExecutionRecord(
        step_id=step.step_id,
        tool_name=step.tool_name,
        tool_args=step.tool_args,
        status=step_status,
        output=final_output,
        error=tool_result.error,
        duration_ms=tool_result.duration_ms,
        rollback_context=tool_result.rollback_context,
        timestamp=datetime.now(UTC),
    )

    exec_desc = (
        f"Operación '{op_label}' ejecutada {'con éxito' if tool_result.success else 'con fallo'} "
        f"en {tool_result.duration_ms:.2f}ms."
    )
    if not tool_result.success and tool_result.error:
        exec_desc += f" Detalle: {tool_result.error}"

    exec_step = CognitiveStepRecord(
        step_id=f"cog_exec_{step.step_id}",
        node="execute",
        title=f"Ejecución de Acción: {op_label}",
        action=f"Invocación de {op_label}",
        description=exec_desc,
        status="completed" if tool_result.success else "failed",
        details={
            "tool_name": step.tool_name,
            "tool_args": step.tool_args,
            "output": tool_result.output,
            "error": tool_result.error,
            "duration_ms": tool_result.duration_ms,
            "rollback_context": tool_result.rollback_context,
        },
        duration_ms=tool_result.duration_ms,
        timestamp=datetime.now(UTC),
    )

    msg_content = (
        str(tool_result.output)
        if tool_result.success
        else f"Error ejecutando {tool.name}: {tool_result.error}"
    )
    max_tool_msg_chars = 2500
    if len(msg_content) > max_tool_msg_chars:
        half_tool = max_tool_msg_chars // 2
        msg_content = (
            msg_content[:half_tool]
            + f"\n... [omisión central ({len(msg_content)} chars)] ...\n"
            + msg_content[-half_tool:]
        )
    tool_msg = ToolMessage(content=msg_content, tool_call_id=step.step_id, name=step.tool_name)

    err: ExecutionError | None = None
    if not tool_result.success:
        err_desc = tool_result.error or f"Fallo en la ejecución de '{step.tool_name}'."
        is_timeout = bool(tool_result.metadata.get("timed_out"))
        allow_fail = bool(
            getattr(step, "allow_failure", False)
            or (tool and getattr(tool, "allow_failure", False))
        )
        err = ExecutionError(
            code="TOOL_TIMEOUT" if is_timeout else "TOOL_EXECUTION_FAILED",
            message=err_desc,
            component="execute",
            fatal=not allow_fail,
        )

    return record, sec_step, exec_step, tool_msg, err
