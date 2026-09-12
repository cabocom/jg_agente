"""Nodo ejecutor de herramientas (execute) para jg_agente.

Ejecuta de forma secuencial las herramientas autorizadas, bien procedan de un plan
estructurado (ExecutionPlan) o de llamadas a herramientas emitidas por el LLM (tool_calls).
Interpola las directivas de seguridad a través de SecurityGuard, mide tiempos de ejecución,
captura fallos operacionales y preserva el contexto de compensación (rollback_context).
"""

import asyncio
import inspect
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import ToolMessage

from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    AuditRecord,
    CognitiveStepRecord,
    ExecutionError,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    StepExecutionRecord,
    StepStatus,
)
from app.models.tools import RiskLevel, ToolResult
from app.security.guard import SecurityGuard, get_security_guard

logger = logging.getLogger("jg_agente.nodes.execute")


async def execute_node(
    state: AgentState,
    registry: CapabilityRegistry,
    security_guard: SecurityGuard | None = None,
) -> dict[str, Any]:
    """Ejecuta secuencialmente herramientas autorizadas bajo sandbox y gobernanza HITL.

    Args:
        state: Estado global actual del agente (AgentState).
        registry: Catálogo de capacidades para localizar las herramientas requeridas.
        security_guard: Interceptor de seguridad opcional (usa singleton por defecto).

    Returns:
        Diccionario con las mutaciones de estado para LangGraph (execution_records,
        errors, messages, audit_trail, status, y plan actualizado).
    """
    guard = security_guard or get_security_guard()

    # 1. Metadatos de contexto de ejecución
    execution_id: str | None = None
    thread_id: str | None = None
    req = state.get("request")
    if req:
        execution_id = getattr(req, "execution_id", None)
        thread_id = getattr(req, "thread_id", None)

    # 2. Comprobar autorización humana previa (HITL) granular [AGENTE-SEC-05]
    approval_val = state.get("approval")
    approval_status: ApprovalStatus | str | None = None
    approved_step_ids: set[str] = set()
    approved_tool_names: set[str] = set()

    if isinstance(approval_val, ApprovalRecord):
        approval_status = approval_val.status
        if approval_val.approved_step_ids:
            approved_step_ids.update(approval_val.approved_step_ids)
        if approval_val.approved_tool_names:
            approved_tool_names.update(approval_val.approved_tool_names)
    elif isinstance(approval_val, dict):
        approval_status = approval_val.get("status")
        if approval_val.get("approved_step_ids"):
            approved_step_ids.update(approval_val["approved_step_ids"])
        if approval_val.get("approved_tool_names"):
            approved_tool_names.update(approval_val["approved_tool_names"])

    state_steps = state.get("approved_step_ids")
    if state_steps:
        approved_step_ids.update(state_steps)
    state_tools = state.get("approved_tool_names")
    if state_tools:
        approved_tool_names.update(state_tools)

    is_plan_approved = approval_status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.APPROVED.value,
        ApprovalStatus.AUTO_APPROVED,
        ApprovalStatus.AUTO_APPROVED.value,
    )

    caller_perms: list[str] = []
    state_perms = state.get("caller_permissions")
    if state_perms:
        caller_perms = list(state_perms)
    elif req and req.user_context:
        if req.user_context.role == "admin" or (
            getattr(req, "metadata", None) and req.metadata.get("user_role") == "admin"
        ):
            caller_perms = ["*"]
        elif req.user_context.permissions:
            caller_perms = list(req.user_context.permissions)

    # 3. Determinar los pasos u operaciones a ejecutar
    raw_plan = state.get("plan")
    plan: ExecutionPlan | None = None
    steps_to_run: list[PlanStep] = []

    if isinstance(raw_plan, ExecutionPlan):
        plan = raw_plan
        steps_to_run = list(plan.steps)
    elif isinstance(raw_plan, dict) and "steps" in raw_plan:
        plan = ExecutionPlan(**raw_plan)
        steps_to_run = list(plan.steps)

    # Si no hay plan estructurado, inspeccionar llamadas directas de herramienta (tool_calls)
    if not steps_to_run:
        intent_val = state.get("intent")
        tool_calls: list[dict[str, Any]] = []
        if isinstance(intent_val, IntentModel) and intent_val.parameters:
            tool_calls = intent_val.parameters.get("tool_calls", [])
        elif isinstance(intent_val, dict) and "parameters" in intent_val:
            tool_calls = intent_val.get("parameters", {}).get("tool_calls", [])

        if tool_calls:
            for idx, tc in enumerate(tool_calls, start=1):
                call_id = tc.get("id") or f"call_{idx}"
                name = tc.get("name", "")
                args = tc.get("args") or {}
                if isinstance(args, str):
                    try:
                        import json

                        args = json.loads(args)
                    except Exception:
                        args = {"input": args}
                tool_def = registry.get_tool(name)
                risk = tool_def.risk_level if tool_def else RiskLevel.LOW
                rev = tool_def.reversible if tool_def else False
                steps_to_run.append(
                    PlanStep(
                        step_id=call_id,
                        tool_name=name,
                        tool_args=args,
                        description=f"Ejecución directa de {name}",
                        risk_level=risk,
                        reversible=rev,
                    )
                )

    # 4. Ejecución secuencial de herramientas
    records: list[StepExecutionRecord] = []
    cognitive_steps: list[CognitiveStepRecord] = []
    errors: list[ExecutionError] = []
    tool_messages: list[ToolMessage] = []

    for step in steps_to_run:
        tool = registry.get_tool(step.tool_name)
        if not tool:
            err_msg = f"La herramienta '{step.tool_name}' no existe en el CapabilityRegistry."
            logger.error("[execute_node] Error: %s", err_msg)
            err = ExecutionError(
                code="TOOL_NOT_FOUND",
                message=err_msg,
                component="execute",
                fatal=True,
            )
            errors.append(err)
            step.status = StepStatus.FAILED
            records.append(
                StepExecutionRecord(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    tool_args=step.tool_args,
                    status=StepStatus.FAILED,
                    error=err_msg,
                    duration_ms=0.0,
                    timestamp=datetime.now(UTC),
                )
            )
            cognitive_steps.append(
                CognitiveStepRecord(
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
            )
            # Contención secuencial: abortar pasos subsiguientes
            break

        step.status = StepStatus.RUNNING
        logger.info(
            "[execute_node] Ejecutando paso '%s' con herramienta '%s' (riesgo: %s, reversible: %s)",
            step.step_id,
            tool.name,
            tool.risk_level.value,
            tool.reversible,
        )

        # Autorización granular por paso [AGENTE-SEC-05]:
        # bypass_approval solo es True para los pasos o herramientas explícitamente aprobados
        step_bypass_approval = False
        if is_plan_approved:
            if approved_step_ids or approved_tool_names:
                step_bypass_approval = (
                    step.step_id in approved_step_ids or step.tool_name in approved_tool_names
                )
            else:
                # Si se aprobó el plan globalmente sin lista y solo hay un paso, se aprueba dicho paso
                step_bypass_approval = len(steps_to_run) == 1

        # Salto cognitivo: Evaluación de Políticas de Seguridad (SecurityGuard)
        sec_description = (
            f"Operación '{tool.name}' evaluada con riesgo {tool.risk_level.value.upper()}. "
            f"{'Autorizada previamente vía HITL.' if step_bypass_approval else 'Política: Ejecución autónoma autorizada (ALLOW).'}"
        )
        cognitive_steps.append(
            CognitiveStepRecord(
                step_id=f"cog_sec_{step.step_id}",
                node="security_eval",
                title="Evaluación de Seguridad y Gobernanza (SecurityGuard)",
                action=f"Auditoría de Políticas: {tool.name}",
                description=sec_description,
                status="completed",
                details={
                    "tool": tool.name,
                    "risk_level": tool.risk_level.value,
                    "decision": "allow",
                    "bypass_approval": step_bypass_approval,
                    "reversible": tool.reversible,
                },
                duration_ms=0.0,
                timestamp=datetime.now(UTC),
            )
        )

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
                ),
                timeout=timeout_sec,
            )
        except TimeoutError:
            err_desc = (
                f"TimeoutError: La ejecución del paso '{step.step_id}' con herramienta "
                f"'{tool.name}' superó el límite de {timeout_sec}s."
            )
            logger.warning("[execute_node] %s", err_desc)
            tool_result = ToolResult(
                success=False,
                error=err_desc,
                duration_ms=timeout_sec * 1000.0,
                metadata={"timeout_sec": timeout_sec, "timed_out": True},
            )

        # Soporte para herramientas que devuelven corrutinas (retrocompatibilidad)
        if inspect.iscoroutine(tool_result.output):
            try:
                tool_result.output = await asyncio.wait_for(
                    tool_result.output,
                    timeout=timeout_sec,
                )
            except TimeoutError:
                err_desc = (
                    f"TimeoutError: La corrutina de salida de '{tool.name}' "
                    f"superó el límite de {timeout_sec}s."
                )
                logger.warning("[execute_node] %s", err_desc)
                tool_result = ToolResult(
                    success=False,
                    error=err_desc,
                    duration_ms=timeout_sec * 1000.0,
                    metadata={"timeout_sec": timeout_sec, "timed_out": True},
                )

        step_status = StepStatus.COMPLETED if tool_result.success else StepStatus.FAILED
        step.status = step_status

        record = StepExecutionRecord(
            step_id=step.step_id,
            tool_name=step.tool_name,
            tool_args=step.tool_args,
            status=step_status,
            output=tool_result.output,
            error=tool_result.error,
            duration_ms=tool_result.duration_ms,
            rollback_context=tool_result.rollback_context,
            timestamp=datetime.now(UTC),
        )
        records.append(record)

        # Salto cognitivo: Ejecución técnica de la acción
        exec_description = (
            f"Herramienta '{tool.name}' ejecutada {'con éxito' if tool_result.success else 'con fallo'} "
            f"en {tool_result.duration_ms:.2f}ms."
        )
        cognitive_steps.append(
            CognitiveStepRecord(
                step_id=f"cog_exec_{step.step_id}",
                node="execute",
                title=f"Ejecución de Acción: {tool.name}",
                action=f"Invocación de {tool.name}",
                description=exec_description,
                status="completed" if tool_result.success else "failed",
                details={
                    "tool_name": step.tool_name,
                    "tool_args": step.tool_args,
                    "output": tool_result.output,
                    "error": tool_result.error,
                    "duration_ms": tool_result.duration_ms,
                },
                duration_ms=tool_result.duration_ms,
                timestamp=datetime.now(UTC),
            )
        )

        # Emitir ToolMessage para la memoria conversacional y re-evaluación del LLM
        msg_content = (
            str(tool_result.output)
            if tool_result.success
            else f"Error ejecutando {tool.name}: {tool_result.error}"
        )
        max_tool_msg_chars = 8000
        if len(msg_content) > max_tool_msg_chars:
            msg_content = (
                msg_content[:max_tool_msg_chars]
                + f"\n... [Salida truncada a {max_tool_msg_chars} caracteres para prevenir saturación de contexto]"
            )
        tool_messages.append(
            ToolMessage(
                content=msg_content,
                tool_call_id=step.step_id,
                name=step.tool_name,
            )
        )

        # Manejo de fallos operacionales
        if not tool_result.success:
            err_desc = tool_result.error or f"Fallo en la ejecución de '{step.tool_name}'."
            logger.warning(
                "[execute_node] Paso '%s' falló: %s",
                step.step_id,
                err_desc,
            )
            is_timeout = bool(tool_result.metadata.get("timed_out"))
            errors.append(
                ExecutionError(
                    code="TOOL_TIMEOUT" if is_timeout else "TOOL_EXECUTION_FAILED",
                    message=err_desc,
                    component="execute",
                    fatal=False,
                )
            )
            # Contención secuencial: abortar pasos posteriores tras el primer fallo
            break

    # 5. Consolidación de mutaciones de estado
    success_count = sum(1 for r in records if r.status == StepStatus.COMPLETED)
    failed_count = sum(1 for r in records if r.status == StepStatus.FAILED)

    mutations: dict[str, Any] = {
        "status": AgentExecutionStatus.EXECUTING,
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
