# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo de verificación post-ejecución (verify_node) para jg_agente."""

import inspect
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.async_compat import is_awaitable_or_coroutine
from app.core.registry import CapabilityRegistry
from app.models.enums import StepStatus
from app.models.records import (
    AuditRecord,
    CognitiveStepRecord,
    ExecutionError,
)
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    VerificationStatus,
)

logger = logging.getLogger("jg_agente.nodes.verify")


def _parse_engine_verification_result(
    v_res: Any,
    details: dict[str, Any],
) -> VerificationStatus:
    """Interpreta polimórficamente la salida devuelta por VerifierEngine."""
    if isinstance(v_res, dict):
        details.update(v_res)
        if "status" in v_res:
            raw_st = v_res["status"]
            return (
                raw_st
                if isinstance(raw_st, VerificationStatus)
                else VerificationStatus(str(raw_st).lower())
            )
        if "success" in v_res:
            return VerificationStatus.PASS if v_res["success"] else VerificationStatus.FAIL
        if "passed" in v_res:
            return VerificationStatus.PASS if v_res["passed"] else VerificationStatus.FAIL
    elif isinstance(v_res, VerificationStatus):
        return v_res
    elif isinstance(v_res, bool):
        return VerificationStatus.PASS if v_res else VerificationStatus.FAIL
    elif v_res is not None:
        details["engine_output"] = str(v_res)
    return VerificationStatus.PASS


async def _invoke_verifier_engine(
    verifier: Any,
    state: AgentState,
) -> tuple[VerificationStatus, dict[str, Any]]:
    """Invoca el motor VerifierEngine y captura excepciones."""
    records = list(state.get("execution_records") or [])
    details: dict[str, Any] = {
        "verified_by": getattr(verifier, "name", "core"),
        "steps_checked": len(records),
    }
    verify_fn = getattr(verifier, "verify", None) or getattr(verifier, "verify_execution", None)
    if not callable(verify_fn):
        logger.warning("VerifierEngine '%s' no implementa método verify invocable.", verifier.name)
        return VerificationStatus.PASS, details

    try:
        sig = inspect.signature(verify_fn)
        call_with_state = len(sig.parameters) > 0
    except (TypeError, ValueError):
        call_with_state = True

    try:
        res = verify_fn(state) if call_with_state else verify_fn()
        v_res = await res if is_awaitable_or_coroutine(res) else res
        v_status = _parse_engine_verification_result(v_res, details)
        return v_status, details
    except Exception as exc:
        logger.exception("Excepción en VerifierEngine '%s': %s", verifier.name, exc)
        details["error"] = str(exc)
        return VerificationStatus.FAIL, details


def _build_verification_mutation(
    v_status: VerificationStatus,
    details: dict[str, Any],
    duration_ms: float,
) -> dict[str, Any]:
    """Formula el resultado consolidado del nodo de verificación."""
    details["duration_ms"] = duration_ms
    is_failed = v_status in (VerificationStatus.FAIL, VerificationStatus.DEGRADED)
    verifier_name = str(details.get("verified_by", "core"))

    audit = AuditRecord(
        event_type="verification_failed" if is_failed else "verification_completed",
        actor=verifier_name,
        details={"status": v_status.value, "details": details, "duration_ms": duration_ms},
    )
    cog_step = CognitiveStepRecord(
        step_id=f"cog_verify_{int(time.time() * 1000)}",
        node="verify",
        title=f"Verificación Post-Ejecución ({verifier_name})",
        action=f"Comprobación de Estado: {v_status.value.upper()}",
        description=str(
            details.get("reason")
            or details.get("error")
            or f"Verificación del sistema completada con veredicto '{v_status.value.upper()}'."
        ),
        status="completed" if not is_failed else "failed",
        details={"status": v_status.value, "verified_by": verifier_name, "details": details},
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )
    res: dict[str, Any] = {
        "status": AgentExecutionStatus.VERIFYING,
        "verification_results": [
            {
                "status": v_status.value,
                "timestamp": datetime.now(UTC).isoformat(),
                "details": details,
            }
        ],
        "cognitive_steps": [cog_step],
        "audit_trail": [audit],
    }
    if is_failed:
        res["errors"] = [
            ExecutionError(
                code="VERIFICATION_FAILED",
                message=str(
                    details.get("reason") or details.get("error") or "Anomalía post-ejecución"
                ),
                component="verify",
                fatal=False,
            )
        ]
    return res


async def verify_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Ejecuta la comprobación post-ejecución del estado del agente y del entorno."""
    start_time = time.perf_counter()
    verifier = registry.get_verifier() if registry else None
    records = list(state.get("execution_records") or [])
    errors = list(state.get("errors") or [])
    has_failed = any(getattr(r, "status", None) == StepStatus.FAILED for r in records)
    has_fatal = any(getattr(e, "fatal", False) for e in errors)

    if verifier is not None:
        v_status, details = await _invoke_verifier_engine(verifier, state)
    else:
        v_status = VerificationStatus.FAIL if (has_failed or has_fatal) else VerificationStatus.PASS
        details = {
            "verified_by": "core",
            "steps_checked": len(records),
            "fallback": True,
            "reason": (
                "Anomalías detectadas en registros previos."
                if (has_failed or has_fatal)
                else "Comprobación básica autónoma superada."
            ),
        }

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return _build_verification_mutation(v_status, details, duration_ms)
