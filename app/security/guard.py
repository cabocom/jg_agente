"""Interceptor central de seguridad (SecurityGuard) para jg_agente.

Interpone una capa de seguridad determinista previa a la invocación de herramientas:
1. Verificación estricta de permisos del llamador frente a required_permissions.
2. Sanitización y detección de inyecciones de comandos shell y directory traversal.
3. Inspección profunda de destinos de red contra ataques SSRF (SSRFValidator).
4. Puerta de enlace de riesgo (HITL) para herramientas HIGH o CRITICAL.
5. Auditoría inmutable de todas las decisiones y ejecuciones (SecurityAuditLogger).
"""

import asyncio
import inspect
import logging
import re
import time
from collections.abc import Sequence
from typing import Any

from app.models.state import PolicyDecision, SecurityEvaluationResult
from app.models.tools import AgentTool, RiskLevel, ToolResult

logger = logging.getLogger("jg_agente.security.guard")

# Metacaracteres y secuencias sospechosas de inyección de comandos shell
SHELL_INJECTION_PATTERN = re.compile(r"[;&$`\n\r><|\\'\"]")

# Directorios del sistema de archivos protegidos
PROTECTED_SYSTEM_PATHS = (
    "/etc",
    "/boot",
    "/root",
    "/sys",
    "/proc",
    "/dev",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/var/run",
)


class SecurityGuard:
    """Interceptor y sandbox de ejecución para herramientas del Core de jg_agente."""

    def __init__(
        self,
        audit_logger: Any | None = None,
        ssrf_validator: Any | None = None,
    ) -> None:
        from app.security.audit import get_security_audit_logger
        from app.security.ssrf import get_ssrf_validator

        self.audit_logger = audit_logger or get_security_audit_logger()
        self.ssrf_validator = ssrf_validator or get_ssrf_validator()

    def sanitize_arguments(self, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Sanitiza y normaliza argumentos de entrada para herramientas.

        Limpia espacios innecesarios y normaliza cadenas de texto.
        """
        sanitized: dict[str, Any] = {}
        for key, value in tool_args.items():
            if isinstance(value, str):
                # Limpiar caracteres nulos y espacios extremos
                clean_val = value.replace("\x00", "").strip()
                sanitized[key] = clean_val
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_arguments(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    v.replace("\x00", "").strip() if isinstance(v, str) else v for v in value
                ]
            else:
                sanitized[key] = value
        return sanitized

    def evaluate(
        self,
        tool: AgentTool | str,
        tool_args: dict[str, Any],
        risk_level: RiskLevel | None = None,
        required_permissions: Sequence[str] | None = None,
        makes_http_requests: bool = False,
        caller_permissions: Sequence[str] | None = None,
        is_reversible: bool = False,
        execution_id: str | None = None,
    ) -> SecurityEvaluationResult:
        """Evalúa las políticas de seguridad de una operación previa a su ejecución física.

        Determina si la operación es ALLOW, DENY o REQUIRE_HUMAN_APPROVAL y
        registra la decisión en la auditoría inmutable.
        """
        if isinstance(tool, AgentTool):
            tool_name = tool.name
            effective_risk = risk_level or tool.risk_level
            effective_perms = (
                list(required_permissions)
                if required_permissions is not None
                else list(tool.required_permissions)
            )
            effective_http = makes_http_requests or tool.makes_http_requests
            effective_reversible = is_reversible or tool.reversible
        else:
            tool_name = str(tool)
            effective_risk = risk_level or RiskLevel.LOW
            effective_perms = list(required_permissions or [])
            effective_http = makes_http_requests
            effective_reversible = is_reversible

        # Determinar el recurso objetivo
        target_resource = str(
            tool_args.get("target_url")
            or tool_args.get("url")
            or tool_args.get("target")
            or tool_name
        )

        # 1. Comprobación de Permisos del Invocador
        if effective_perms:
            caller_perms_set = set(caller_permissions or [])
            if "*" not in caller_perms_set and "admin" not in caller_perms_set:
                missing_perms = [p for p in effective_perms if p not in caller_perms_set]
                if missing_perms:
                    reason = (
                        f"Permisos insuficientes para ejecutar '{tool_name}'. "
                        f"Faltan permisos requeridos: {missing_perms}"
                    )
                    logger.warning("SecurityGuard DENY en '%s': %s", tool_name, reason)
                    eval_res = SecurityEvaluationResult(
                        decision=PolicyDecision.DENY,
                        operation=tool_name,
                        target_resource=target_resource,
                        risk_level=effective_risk,
                        reason=reason,
                        required_permissions=effective_perms,
                        is_reversible=effective_reversible,
                        can_cause_data_loss=False,
                    )
                    self.audit_logger.record(eval_res, execution_id=execution_id)
                    return eval_res

        # 2. Comprobación de Inyección de Comandos Shell y Directory Traversal
        for arg_key, arg_val in tool_args.items():
            if isinstance(arg_val, str):
                # Comprobación de Directory Traversal en argumentos de ruta o archivos
                if ".." in arg_val or arg_val.startswith("/proc") or arg_val.startswith("/etc"):
                    for sys_path in PROTECTED_SYSTEM_PATHS:
                        if arg_val == sys_path or arg_val.startswith(sys_path + "/"):
                            reason = (
                                f"Violación de seguridad: Acceso denegado a ruta de sistema "
                                f"protegida '{arg_val}' en argumento '{arg_key}'"
                            )
                            logger.error("SecurityGuard DENY en '%s': %s", tool_name, reason)
                            eval_res = SecurityEvaluationResult(
                                decision=PolicyDecision.DENY,
                                operation=tool_name,
                                target_resource=target_resource,
                                risk_level=RiskLevel.HIGH,
                                reason=reason,
                                required_permissions=effective_perms,
                                is_reversible=False,
                                can_cause_data_loss=True,
                            )
                            self.audit_logger.record(eval_res, execution_id=execution_id)
                            return eval_res

                # Comprobación de Inyección de Comandos en identificadores o comandos
                if (
                    "command" in arg_key
                    or "name" in arg_key
                    or "service" in arg_key
                    or "host" in arg_key
                ) and SHELL_INJECTION_PATTERN.search(arg_val):
                    reason = (
                        f"Violación de seguridad: Caracteres sospechosos de inyección "
                        f"shell detectados en argumento '{arg_key}': '{arg_val}'"
                    )
                    logger.error("SecurityGuard DENY en '%s': %s", tool_name, reason)
                    eval_res = SecurityEvaluationResult(
                        decision=PolicyDecision.DENY,
                        operation=tool_name,
                        target_resource=target_resource,
                        risk_level=RiskLevel.HIGH,
                        reason=reason,
                        required_permissions=effective_perms,
                        is_reversible=False,
                        can_cause_data_loss=True,
                    )
                    self.audit_logger.record(eval_res, execution_id=execution_id)
                    return eval_res

        # 3. Comprobación de Seguridad SSRF para Tools de Red
        if effective_http:
            is_safe, ssrf_reason = self.ssrf_validator.validate_tool_arguments_for_ssrf(
                tool_name=tool_name,
                args=tool_args,
                makes_http_requests=True,
            )
            if not is_safe:
                reason = f"Bloqueo de seguridad SSRF: {ssrf_reason}"
                logger.error("SecurityGuard DENY en '%s': %s", tool_name, reason)
                eval_res = SecurityEvaluationResult(
                    decision=PolicyDecision.DENY,
                    operation=tool_name,
                    target_resource=target_resource,
                    risk_level=RiskLevel.HIGH,
                    reason=reason,
                    required_permissions=effective_perms,
                    is_reversible=False,
                    can_cause_data_loss=False,
                )
                self.audit_logger.record(eval_res, execution_id=execution_id)
                return eval_res

        # 4. Evaluación de Niveles de Riesgo y Puerta Human-In-The-Loop (HITL)
        if effective_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            reason = (
                f"Operación de riesgo {effective_risk.value.upper()} '{tool_name}' "
                f"requiere autorización humana previa (HITL)."
            )
            logger.warning("SecurityGuard REQUIRE_HUMAN_APPROVAL en '%s': %s", tool_name, reason)
            eval_res = SecurityEvaluationResult(
                decision=PolicyDecision.REQUIRE_HUMAN_APPROVAL,
                operation=tool_name,
                target_resource=target_resource,
                risk_level=effective_risk,
                reason=reason,
                required_permissions=effective_perms,
                is_reversible=effective_reversible,
                can_cause_data_loss=(effective_risk == RiskLevel.CRITICAL),
            )
            self.audit_logger.record(eval_res, execution_id=execution_id)
            return eval_res

        # 5. Operación Autorizada (ALLOW)
        reason = f"Operación '{tool_name}' (riesgo {effective_risk.value}) autorizada para ejecución autónoma."
        eval_res = SecurityEvaluationResult(
            decision=PolicyDecision.ALLOW,
            operation=tool_name,
            target_resource=target_resource,
            risk_level=effective_risk,
            reason=reason,
            required_permissions=effective_perms,
            is_reversible=effective_reversible,
            can_cause_data_loss=False,
        )
        self.audit_logger.record(eval_res, execution_id=execution_id)
        return eval_res

    async def execute_tool(
        self,
        tool: AgentTool,
        tool_args: dict[str, Any],
        caller_permissions: Sequence[str] | None = None,
        bypass_approval: bool = False,
        execution_id: str | None = None,
        thread_id: str | None = None,
    ) -> ToolResult:
        """Interpola validación de seguridad, sanitización, timeout y auditoría antes de invocar la tool.

        - Si la decisión es DENY: Devuelve ToolResult con fallo sin invocar la función.
        - Si la decisión es REQUIRE_HUMAN_APPROVAL: Devuelve ToolResult señalizando pausa HITL (salvo bypass_approval=True).
        - Si la decisión es ALLOW (o aprobada): Sanitiza entradas, ejecuta bajo asyncio.wait_for(timeout=tool.timeout_sec)
          sin bloquear los workers del agente, y audita el resultado.
        """
        caller_perms = list(caller_permissions or [])
        if bypass_approval and isinstance(tool, AgentTool):
            caller_perms.extend(tool.required_permissions)

        eval_res = self.evaluate(
            tool=tool,
            tool_args=tool_args,
            caller_permissions=caller_perms,
            execution_id=execution_id,
        )

        if eval_res.decision == PolicyDecision.DENY:
            return ToolResult(
                success=False,
                error=f"SecurityGuard DENY: {eval_res.reason}",
                duration_ms=0.0,
                metadata={
                    "security_decision": eval_res.decision.value,
                    "risk_level": eval_res.risk_level.value,
                    "reason": eval_res.reason,
                },
            )

        if eval_res.decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL and not bypass_approval:
            return ToolResult(
                success=False,
                error=f"SecurityGuard REQUIRE_HUMAN_APPROVAL: {eval_res.reason}",
                duration_ms=0.0,
                metadata={
                    "security_decision": eval_res.decision.value,
                    "risk_level": eval_res.risk_level.value,
                    "requires_approval": True,
                    "reason": eval_res.reason,
                },
            )

        # Decisión ALLOW (o HITL aprobado): Sanitizar entradas e invocar físicamente la herramienta con timeout
        sanitized_args = self.sanitize_arguments(tool_args)
        start_time = time.perf_counter()
        timeout_sec = getattr(tool, "timeout_sec", 30.0) or 30.0

        try:

            def _invoke_sync() -> Any:
                try:
                    return tool.func(**sanitized_args)
                except TypeError:
                    if tool.args_schema:
                        parsed_args = tool.args_schema(**sanitized_args)
                        return tool.func(parsed_args)
                    raise

            if inspect.iscoroutinefunction(tool.func):

                async def _invoke_async() -> Any:
                    try:
                        return await tool.func(**sanitized_args)
                    except TypeError:
                        if tool.args_schema:
                            parsed_args = tool.args_schema(**sanitized_args)
                            return await tool.func(parsed_args)
                        raise

                raw_res = await asyncio.wait_for(_invoke_async(), timeout=timeout_sec)
            else:
                raw_res = await asyncio.wait_for(
                    asyncio.to_thread(_invoke_sync),
                    timeout=timeout_sec,
                )
                if inspect.iscoroutine(raw_res):
                    raw_res = await asyncio.wait_for(raw_res, timeout=timeout_sec)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            if isinstance(raw_res, ToolResult):
                tool_res = raw_res
                if tool_res.duration_ms <= 0.0:
                    tool_res.duration_ms = duration_ms
            else:
                tool_res = ToolResult(
                    success=True,
                    output=raw_res,
                    duration_ms=duration_ms,
                )
        except TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = (
                f"TimeoutError: La herramienta '{tool.name}' superó el tiempo límite "
                f"de {timeout_sec}s."
            )
            logger.warning("[SecurityGuard] %s", err_msg)
            tool_res = ToolResult(
                success=False,
                error=err_msg,
                duration_ms=duration_ms,
                metadata={"timeout_sec": timeout_sec, "timed_out": True},
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.exception("Fallo en ejecución de tool '%s': %s", tool.name, exc)
            tool_res = ToolResult(
                success=False,
                error=f"Excepción durante la ejecución de '{tool.name}': {exc}",
                duration_ms=duration_ms,
                metadata={"exception": str(exc)},
            )

        # Auditoría inmutable de la ejecución de la herramienta
        self.audit_logger.record_tool_execution(
            tool_name=tool.name,
            tool_args=sanitized_args,
            result=tool_res,
            risk_level=tool.risk_level,
            execution_id=execution_id,
            thread_id=thread_id,
        )

        return tool_res


# Instancia singleton por defecto
_default_security_guard: SecurityGuard | None = None


def get_security_guard() -> SecurityGuard:
    """Factory singleton para SecurityGuard."""
    global _default_security_guard
    if _default_security_guard is None:
        _default_security_guard = SecurityGuard()
    return _default_security_guard
