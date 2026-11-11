# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Interceptor central de seguridad (SecurityGuard) para jg_agente."""

import logging
import threading
from collections.abc import Sequence
from typing import Any

from app.models.state import PolicyDecision, SecurityEvaluationResult
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.security.guard_policy import (
    DEGRADED_CHECKPOINT_DENY_REASON,
    evaluate_security_policy,
)
from app.security.sanitizer import (
    PROTECTED_SYSTEM_PATHS,
    SHELL_INJECTION_PATTERN,
    URL_SHELL_INJECTION_PATTERN,
)
from app.security.sanitizer import (
    build_protected_paths as _build_protected_paths,
)
from app.security.sanitizer import (
    check_argument_security_violations as _check_arg_violations,
)
from app.security.sanitizer import (
    check_directory_traversal_or_protected_path as _check_directory_traversal_or_protected_path,
)
from app.security.sanitizer import (
    check_workspace_escape as _check_workspace_escape,
)
from app.security.sanitizer import (
    extract_string_arguments as _extract_string_arguments,
)
from app.security.sanitizer import (
    sanitize_arguments as _sanitize_args_func,
)
from app.security.tool_executor import invoke_tool_safely

logger = logging.getLogger("jg_agente.security.guard")


def _resolve_bypass_and_permissions(
    tool: AgentTool,
    caller_permissions: Sequence[str] | None,
    bypass_approval: bool,
    step_id: str | None,
    approved_step_ids: Sequence[str] | None,
    approved_tool_names: Sequence[str] | None,
) -> tuple[bool, list[str]]:
    """Calcula si aplica bypass de aprobación y amplía permisos de invocador si procede."""
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
    if effective_bypass and not isinstance(tool, str) and hasattr(tool, "required_permissions"):
        caller_perms.extend(tool.required_permissions)
    return effective_bypass, caller_perms


def _handle_guard_block(
    eval_res: SecurityEvaluationResult, effective_bypass: bool
) -> ToolResult | None:
    """Verifica si la decisión de seguridad bloquea la ejecución de la herramienta."""
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
    return None


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
        """Sanitiza y normaliza argumentos de entrada para herramientas."""
        return _sanitize_args_func(tool_args)

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
        """Evalúa las políticas de seguridad previas a la ejecución de una herramienta."""
        eval_res = evaluate_security_policy(
            tool=tool,
            tool_args=tool_args,
            risk_level=risk_level,
            required_permissions=required_permissions,
            makes_http_requests=makes_http_requests,
            caller_permissions=caller_permissions,
            is_reversible=is_reversible,
            workspace_dir=workspace_dir,
            checkpoint_degraded=checkpoint_degraded,
            ssrf_validator=self.ssrf_validator,
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
        """Interpola validación de seguridad, sanitización, timeout y auditoría al invocar una tool."""
        effective_bypass, caller_perms = _resolve_bypass_and_permissions(
            tool,
            caller_permissions,
            bypass_approval,
            step_id,
            approved_step_ids,
            approved_tool_names,
        )

        eval_res = self.evaluate(
            tool=tool,
            tool_args=tool_args,
            caller_permissions=caller_perms,
            execution_id=execution_id,
            checkpoint_degraded=checkpoint_degraded,
        )

        block_result = _handle_guard_block(eval_res, effective_bypass)
        if block_result is not None:
            return block_result

        sanitized_args = self.sanitize_arguments(tool_args)
        timeout_sec = getattr(tool, "timeout_sec", 30.0) or 30.0
        tool_res = await invoke_tool_safely(tool, sanitized_args, timeout_sec)

        self.audit_logger.record_tool_execution(
            tool_name=tool.name,
            tool_args=sanitized_args,
            result=tool_res,
            risk_level=tool.risk_level,
            execution_id=execution_id,
            thread_id=thread_id,
        )
        return tool_res


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


__all__ = [
    "DEGRADED_CHECKPOINT_DENY_REASON",
    "PROTECTED_SYSTEM_PATHS",
    "SHELL_INJECTION_PATTERN",
    "SecurityGuard",
    "URL_SHELL_INJECTION_PATTERN",
    "_build_protected_paths",
    "_check_arg_violations",
    "_check_directory_traversal_or_protected_path",
    "_check_workspace_escape",
    "_extract_string_arguments",
    "get_security_guard",
]
