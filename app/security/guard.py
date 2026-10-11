"""Interceptor central de seguridad (SecurityGuard) para jg_agente.

Interpone una capa de seguridad determinista previa a la invocación de herramientas:
1. Verificación estricta de permisos del llamador frente a required_permissions.
2. Sanitización y detección de inyecciones de comandos shell y directory traversal.
3. Inspección profunda de destinos de red contra ataques SSRF (SSRFValidator).
4. Puerta de enlace de riesgo (HITL) para herramientas HIGH o CRITICAL.
5. Auditoría inmutable de todas las decisiones y ejecuciones (SecurityAuditLogger).
"""

import asyncio
import logging
import os
import re
import threading
import time
import urllib.parse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.async_compat import is_awaitable_or_coroutine, is_coroutine_callable
from app.core.config import settings
from app.models.state import PolicyDecision, SecurityEvaluationResult
from app.models.tools import AgentTool, RiskLevel, ToolResult

logger = logging.getLogger("jg_agente.security.guard")

# Motivo canónico de denegación Fail-Closed cuando el checkpointer opera en modo degradado
DEGRADED_CHECKPOINT_DENY_REASON = "Degraded checkpoint mode rejects non-durable high-risk mutations"

# Metacaracteres y secuencias sospechosas de inyección de comandos shell
SHELL_INJECTION_PATTERN = re.compile(r"[;&$`\n\r><|\\'\"]")
# Variante para URLs HTTP/HTTPS donde '&' y comillas son válidos en query strings
URL_SHELL_INJECTION_PATTERN = re.compile(r"[;`$\n\r><|\\]")

# Directorios del sistema de archivos protegidos (base POSIX + rutas canónicas)
_BASE_PROTECTED_SYSTEM_PATHS = (
    "/etc",
    "/boot",
    "/root",
    "/var/root",
    "/sys",
    "/proc",
    "/dev",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/var/run",
    "/run",
    "/private/etc",
    "/private/var/run",
    "/private/var/root",
)


def _build_protected_paths() -> tuple[str, ...]:
    paths: set[str] = set(_BASE_PROTECTED_SYSTEM_PATHS)
    for p in _BASE_PROTECTED_SYSTEM_PATHS:
        try:
            resolved = os.path.realpath(p)
            paths.add(resolved)
        except Exception:
            pass
    return tuple(sorted(paths))


PROTECTED_SYSTEM_PATHS = _build_protected_paths()


def _check_directory_traversal_or_protected_path(arg_val: str) -> tuple[bool, str]:
    """Evalúa si una cadena intenta directory traversal o acceso a rutas de sistema protegidas.

    Aplica normalización canónica (os.path.normpath, os.path.abspath, os.path.realpath)
    para impedir evasiones mediante secuencias '..', barras redundantes, enlaces simbólicos
    o codificación URL.
    """
    if not isinstance(arg_val, str) or not arg_val.strip():
        return False, ""

    val = arg_val.strip()
    # Las URLs HTTP/HTTPS son evaluadas por SSRFValidator, no por el validador de rutas locales
    if val.startswith(("http://", "https://")):
        return False, ""

    # Descodificación de URL para neutralizar bypasses como %2e%2e%2f
    decoded_val = urllib.parse.unquote(val)
    clean_val = decoded_val.replace("\\", "/")

    candidates: list[str] = []

    if clean_val.startswith("/"):
        norm = os.path.normpath(clean_val)
        candidates.append(norm)
        try:
            candidates.append(os.path.realpath(clean_val))
            candidates.append(os.path.realpath(norm))
        except Exception:
            pass
    elif ".." in clean_val:
        # Traversal relativo: verificar escape desde la raíz y desde cwd
        norm_from_root = os.path.normpath(os.path.join("/", clean_val.lstrip("/")))
        candidates.append(norm_from_root)
        try:
            abs_p = os.path.abspath(clean_val)
            candidates.append(abs_p)
            candidates.append(os.path.realpath(abs_p))
            candidates.append(os.path.realpath(norm_from_root))
        except Exception:
            pass
    elif clean_val.startswith("~"):
        try:
            expanded = os.path.expanduser(clean_val)
            candidates.append(expanded)
            candidates.append(os.path.realpath(expanded))
        except Exception:
            pass

    for cand in candidates:
        for sys_path in PROTECTED_SYSTEM_PATHS:
            if cand == sys_path or cand.startswith(sys_path + "/"):
                return True, cand

    return False, ""


def _check_workspace_escape(arg_val: str, workspace_base: str) -> tuple[bool, str]:
    """Comprueba si un argumento tipo ruta escapa del Workspace Jail configurado.

    Resuelve la ruta (symlinks incluidos) relativa al workspace y verifica
    `resolved.is_relative_to(base)`. Devuelve (escapa, ruta_resuelta).
    """
    if not isinstance(arg_val, str) or not arg_val.strip():
        return False, ""

    val = arg_val.strip()
    if val.startswith(("http://", "https://")):
        return False, ""

    clean_val = urllib.parse.unquote(val).replace("\\", "/")
    is_path_like = "/" in clean_val or ".." in clean_val or clean_val.startswith("~")
    if not is_path_like:
        return False, ""

    base = Path(os.path.realpath(workspace_base))
    if clean_val.startswith("~"):
        candidate = Path(os.path.expanduser(clean_val))
    elif clean_val.startswith("/"):
        candidate = Path(clean_val)
    else:
        candidate = base / clean_val

    resolved = Path(os.path.realpath(candidate))
    if resolved.is_relative_to(base):
        return False, ""
    return True, str(resolved)


def _extract_string_arguments(args: Any, parent_key: str = "") -> list[tuple[str, str]]:
    """Extrae recursivamente todas las tuplas (clave_completa, valor_str) de los argumentos."""
    result: list[tuple[str, str]] = []
    if isinstance(args, dict):
        for k, v in args.items():
            full_key = f"{parent_key}.{k}" if parent_key else str(k)
            result.extend(_extract_string_arguments(v, full_key))
    elif isinstance(args, list | tuple | set):
        for idx, item in enumerate(args):
            full_key = f"{parent_key}[{idx}]"
            result.extend(_extract_string_arguments(item, full_key))
    elif isinstance(args, str):
        result.append((parent_key, args))
    return result


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
        workspace_dir: str | None = None,
        checkpoint_degraded: bool = False,
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

        # 1. Comprobación de Permisos del Invocador (RBAC)
        # Desacople de autorización de usuario de restricciones invariantes [AGENTE-SEC-06]:
        # La pertenencia a roles administrativos o permisos wildcard valida exclusivamente
        # los permisos requeridos a nivel de herramienta (RBAC). Bajo ninguna circunstancia
        # exime de las validaciones de inyección, traversal, SSRF o de la gobernanza HITL.
        if effective_perms:
            caller_perms_set = set(caller_permissions or [])
            is_admin_or_wildcard = bool(
                "*" in caller_perms_set
                or "admin" in caller_perms_set
                or "role:admin" in caller_perms_set
            )
            if not is_admin_or_wildcard:
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

        # Fail-Closed: con checkpointer degradado (sin persistencia durable) no puede garantizarse
        # ni la reanudación HITL ni la reversibilidad: se deniegan mutaciones de riesgo alto.
        if checkpoint_degraded and effective_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            reason = DEGRADED_CHECKPOINT_DENY_REASON
            logger.error("SecurityGuard DENY en '%s': %s", tool_name, reason)
            eval_res = SecurityEvaluationResult(
                decision=PolicyDecision.DENY,
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

        # Workspace Jail: confinamiento opcional (parámetro > atributo de la tool > settings)
        jail_base: str | None = (
            workspace_dir
            or (getattr(tool, "workspace_dir", None) if isinstance(tool, AgentTool) else None)
            or getattr(settings, "WORKSPACE_DIR", None)
        )

        # 2. Comprobación Universal de Inyección de Comandos Shell y Directory Traversal
        for arg_key, arg_val in _extract_string_arguments(tool_args):
            if jail_base:
                escapes, resolved_path = _check_workspace_escape(arg_val, jail_base)
                if escapes:
                    reason = (
                        f"Violación de seguridad: Workspace Jail. La ruta '{arg_val}' "
                        f"(resuelta a '{resolved_path}') escapa del workspace confinado "
                        f"en argumento '{arg_key}'"
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
            # Comprobación de Directory Traversal y Acceso a Rutas de Sistema Protegidas
            is_blocked_path, matched_path = _check_directory_traversal_or_protected_path(arg_val)
            if is_blocked_path:
                reason = (
                    f"Violación de seguridad: Acceso denegado a ruta de sistema "
                    f"protegida '{arg_val}' (resuelta a '{matched_path}') en argumento '{arg_key}'"
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

            # Comprobación Universal de Inyección de Comandos Shell (independiente del nombre de la clave)
            is_url = arg_val.startswith(("http://", "https://"))
            pattern_to_use = URL_SHELL_INJECTION_PATTERN if is_url else SHELL_INJECTION_PATTERN
            if pattern_to_use.search(arg_val):
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
        step_id: str | None = None,
        approved_step_ids: Sequence[str] | None = None,
        approved_tool_names: Sequence[str] | None = None,
        checkpoint_degraded: bool = False,
    ) -> ToolResult:
        """Interpola validación de seguridad, sanitización, timeout y auditoría antes de invocar la tool.

        - Si la decisión es DENY: Devuelve ToolResult con fallo sin invocar la función.
        - Si la decisión es REQUIRE_HUMAN_APPROVAL: Devuelve ToolResult señalizando pausa HITL (salvo bypass_approval=True
          y que el step_id/tool.name coincida con los aprobados en approved_step_ids/approved_tool_names).
        - Si la decisión es ALLOW (o aprobada): Sanitiza entradas, ejecuta bajo asyncio.wait_for(timeout=tool.timeout_sec)
          sin bloquear los workers del agente, y audita el resultado.
        """
        # Autorización granular de bypass [AGENTE-SEC-05]
        effective_bypass = bypass_approval
        if bypass_approval:
            has_filter = (approved_step_ids is not None) or (approved_tool_names is not None)
            if has_filter:
                match_step = bool(
                    approved_step_ids is not None
                    and step_id is not None
                    and step_id in approved_step_ids
                )
                match_tool = bool(
                    approved_tool_names is not None
                    and getattr(tool, "name", None) in approved_tool_names
                )
                effective_bypass = match_step or match_tool

        caller_perms = list(caller_permissions or [])
        if effective_bypass and isinstance(tool, AgentTool):
            caller_perms.extend(tool.required_permissions)

        eval_res = self.evaluate(
            tool=tool,
            tool_args=tool_args,
            caller_permissions=caller_perms,
            execution_id=execution_id,
            checkpoint_degraded=checkpoint_degraded,
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

        if eval_res.decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL and not effective_bypass:
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

            if is_coroutine_callable(tool.func):

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
                if is_awaitable_or_coroutine(raw_res):
                    raw_res = await asyncio.wait_for(raw_res, timeout=timeout_sec)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            if isinstance(raw_res, ToolResult):
                tool_res = raw_res
                if is_awaitable_or_coroutine(tool_res.output):
                    tool_res.output = await asyncio.wait_for(tool_res.output, timeout=timeout_sec)
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


# Instancia singleton por defecto y cerrojo de concurrencia
_guard_lock = threading.Lock()
_default_security_guard: SecurityGuard | None = None


def get_security_guard() -> SecurityGuard:
    """Factory singleton thread-safe para SecurityGuard."""
    global _default_security_guard
    if _default_security_guard is None:
        with _guard_lock:
            if _default_security_guard is None:
                _default_security_guard = SecurityGuard()
    return _default_security_guard
