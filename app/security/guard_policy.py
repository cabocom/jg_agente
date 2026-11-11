# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Evaluador de políticas de seguridad, RBAC y gobernanza HITL para SecurityGuard."""

import logging
from collections.abc import Sequence
from typing import Any

from app.core.config import settings
from app.models.state import PolicyDecision, SecurityEvaluationResult
from app.models.tools import AgentTool, RiskLevel
from app.security.sanitizer import check_argument_security_violations

logger = logging.getLogger("jg_agente.security.guard_policy")

DEGRADED_CHECKPOINT_DENY_REASON = "Degraded checkpoint mode rejects non-durable high-risk mutations"


def resolve_tool_parameters(
    tool: AgentTool | str,
    risk_level: RiskLevel | None,
    required_permissions: Sequence[str] | None,
    makes_http_requests: bool,
    is_reversible: bool,
) -> tuple[str, RiskLevel, list[str], bool, bool]:
    """Extrae y normaliza los metadatos declarados en la herramienta o en los argumentos."""
    if not isinstance(tool, str) and hasattr(tool, "name"):
        tool_name = str(tool.name)
        raw_risk = risk_level or getattr(tool, "risk_level", RiskLevel.LOW)
        effective_risk = raw_risk if isinstance(raw_risk, RiskLevel) else RiskLevel.LOW
        effective_perms = (
            list(required_permissions)
            if required_permissions is not None
            else list(getattr(tool, "required_permissions", []) or [])
        )
        effective_http = makes_http_requests or bool(getattr(tool, "makes_http_requests", False))
        effective_rev = is_reversible or bool(getattr(tool, "reversible", False))
    else:
        tool_name = str(tool)
        effective_risk = risk_level if isinstance(risk_level, RiskLevel) else RiskLevel.LOW
        effective_perms = list(required_permissions or [])
        effective_http = makes_http_requests
        effective_rev = is_reversible
    return tool_name, effective_risk, effective_perms, effective_http, effective_rev


def check_caller_rbac(
    effective_perms: list[str],
    caller_permissions: Sequence[str] | None,
    tool_name: str,
) -> str | None:
    """Verifica permisos RBAC del invocador."""
    if not effective_perms:
        return None
    caller_set = set(caller_permissions or [])
    if "*" in caller_set or "admin" in caller_set or "role:admin" in caller_set:
        return None
    missing = [p for p in effective_perms if p not in caller_set]
    if missing:
        return f"Permisos insuficientes para ejecutar '{tool_name}'. Faltan permisos requeridos: {missing}"
    return None


def _check_checkpoint_degraded(
    checkpoint_degraded: bool,
    eff_risk: RiskLevel,
    tool_name: str,
    target: str,
    eff_perms: list[str],
    eff_rev: bool,
) -> SecurityEvaluationResult | None:
    """Deniega mutaciones de alto riesgo si el checkpointer está en modo degradado."""
    if checkpoint_degraded and eff_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        logger.error("SecurityGuard DENY en '%s': %s", tool_name, DEGRADED_CHECKPOINT_DENY_REASON)
        return SecurityEvaluationResult(
            decision=PolicyDecision.DENY,
            operation=tool_name,
            target_resource=target,
            risk_level=eff_risk,
            reason=DEGRADED_CHECKPOINT_DENY_REASON,
            required_permissions=eff_perms,
            is_reversible=eff_rev,
            can_cause_data_loss=(eff_risk == RiskLevel.CRITICAL),
        )
    return None


def _check_argument_sanitization(
    tool: AgentTool | str,
    tool_args: dict[str, Any],
    tool_name: str,
    target: str,
    eff_perms: list[str],
    workspace_dir: str | None,
) -> SecurityEvaluationResult | None:
    """Inspecciona inyección de comandos shell, traversal y jail escape."""
    jail_base = (
        workspace_dir
        or (getattr(tool, "workspace_dir", None) if isinstance(tool, AgentTool) else None)
        or getattr(settings, "WORKSPACE_DIR", None)
    )
    has_violation, violation_reason = check_argument_security_violations(tool_args, jail_base)
    if has_violation:
        logger.error("SecurityGuard DENY en '%s': %s", tool_name, violation_reason)
        return SecurityEvaluationResult(
            decision=PolicyDecision.DENY,
            operation=tool_name,
            target_resource=target,
            risk_level=RiskLevel.HIGH,
            reason=violation_reason,
            required_permissions=eff_perms,
            is_reversible=False,
            can_cause_data_loss=True,
        )
    return None


def _check_ssrf_safety(
    eff_http: bool,
    ssrf_validator: Any,
    tool_name: str,
    tool_args: dict[str, Any],
    target: str,
    eff_perms: list[str],
) -> SecurityEvaluationResult | None:
    """Inspecciona argumentos de herramientas HTTP contra ataques SSRF."""
    if not eff_http:
        return None
    is_safe, ssrf_err = ssrf_validator.validate_tool_arguments_for_ssrf(
        tool_name=tool_name, args=tool_args, makes_http_requests=True
    )
    if not is_safe:
        reason = f"Bloqueo de seguridad SSRF: {ssrf_err}"
        logger.error("SecurityGuard DENY en '%s': %s", tool_name, reason)
        return SecurityEvaluationResult(
            decision=PolicyDecision.DENY,
            operation=tool_name,
            target_resource=target,
            risk_level=RiskLevel.HIGH,
            reason=reason,
            required_permissions=eff_perms,
            is_reversible=False,
            can_cause_data_loss=False,
        )
    return None


def _evaluate_hitl_or_allow(
    eff_risk: RiskLevel,
    tool_name: str,
    target: str,
    eff_perms: list[str],
    eff_rev: bool,
) -> SecurityEvaluationResult:
    """Determina si la operación requiere autorización humana previa o es permitida."""
    action_detail = (
        f"'{tool_name}' ({target})" if target and target != tool_name else f"'{tool_name}'"
    )
    if eff_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        reason = f"Operación de riesgo {eff_risk.value.upper()} {action_detail} requiere autorización humana previa (HITL)."
        logger.warning("SecurityGuard REQUIRE_HUMAN_APPROVAL en '%s': %s", tool_name, reason)
        return SecurityEvaluationResult(
            decision=PolicyDecision.REQUIRE_HUMAN_APPROVAL,
            operation=tool_name,
            target_resource=target,
            risk_level=eff_risk,
            reason=reason,
            required_permissions=eff_perms,
            is_reversible=eff_rev,
            can_cause_data_loss=(eff_risk == RiskLevel.CRITICAL),
        )

    reason = (
        f"Operación {action_detail} (riesgo {eff_risk.value}) autorizada para ejecución autónoma."
    )
    return SecurityEvaluationResult(
        decision=PolicyDecision.ALLOW,
        operation=tool_name,
        target_resource=target,
        risk_level=eff_risk,
        reason=reason,
        required_permissions=eff_perms,
        is_reversible=eff_rev,
        can_cause_data_loss=False,
    )


def evaluate_security_policy(
    tool: AgentTool | str,
    tool_args: dict[str, Any],
    risk_level: RiskLevel | None,
    required_permissions: Sequence[str] | None,
    makes_http_requests: bool,
    caller_permissions: Sequence[str] | None,
    is_reversible: bool,
    workspace_dir: str | None,
    checkpoint_degraded: bool,
    ssrf_validator: Any,
) -> SecurityEvaluationResult:
    """Evalúa las políticas de seguridad previas a la ejecución de una herramienta."""
    tool_name, eff_risk, eff_perms, eff_http, eff_rev = resolve_tool_parameters(
        tool, risk_level, required_permissions, makes_http_requests, is_reversible
    )
    target = str(
        tool_args.get("command")
        or tool_args.get("target_url")
        or tool_args.get("url")
        or tool_args.get("target")
        or tool_name
    )

    rbac_err = check_caller_rbac(eff_perms, caller_permissions, tool_name)
    if rbac_err:
        logger.warning("SecurityGuard DENY en '%s': %s", tool_name, rbac_err)
        return SecurityEvaluationResult(
            decision=PolicyDecision.DENY,
            operation=tool_name,
            target_resource=target,
            risk_level=eff_risk,
            reason=rbac_err,
            required_permissions=eff_perms,
            is_reversible=eff_rev,
            can_cause_data_loss=False,
        )

    chk_res = _check_checkpoint_degraded(
        checkpoint_degraded, eff_risk, tool_name, target, eff_perms, eff_rev
    )
    if chk_res:
        return chk_res

    san_res = _check_argument_sanitization(
        tool, tool_args, tool_name, target, eff_perms, workspace_dir
    )
    if san_res:
        return san_res

    ssrf_res = _check_ssrf_safety(eff_http, ssrf_validator, tool_name, tool_args, target, eff_perms)
    if ssrf_res:
        return ssrf_res

    return _evaluate_hitl_or_allow(eff_risk, tool_name, target, eff_perms, eff_rev)
