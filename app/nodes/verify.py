# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodo de verificación post-ejecución (verify) para jg_agente.

Comprueba activamente los resultados obtenidos tras la ejecución de herramientas mediante
un VerifierEngine de dominio registrado, o aplicando verificación determinista de integridad
sobre execution_records y errores operacionales.
"""

import inspect
import logging
import time
from datetime import UTC, datetime
from typing import Any

from app.core.async_compat import is_awaitable_or_coroutine
from app.core.registry import CapabilityRegistry
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    AuditRecord,
    CognitiveStepRecord,
    ExecutionError,
    StepStatus,
    VerificationStatus,
)

logger = logging.getLogger("jg_agente.nodes.verify")


async def verify_node(
    state: AgentState,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Ejecuta la comprobación post-ejecución del estado del agente y del entorno.

    Args:
        state: Estado global actual del agente (AgentState).
        registry: Catálogo de capacidades opcional.

    Returns:
        Mutaciones del estado para LangGraph (status, verification_results, audit_trail, errors).
    """
    start_time = time.perf_counter()

    verifier = registry.get_verifier() if registry else None
    records = list(state.get("execution_records") or [])
    errors = list(state.get("errors") or [])

    has_failed_records = any(getattr(r, "status", None) == StepStatus.FAILED for r in records)
    has_fatal_errors = any(getattr(e, "fatal", False) for e in errors)

    v_status = (
        VerificationStatus.FAIL
        if (has_failed_records or has_fatal_errors)
        else VerificationStatus.PASS
    )
    details: dict[str, Any] = {
        "verified_by": getattr(verifier, "name", "core") if verifier else "core",
        "steps_checked": len(records),
    }

    # 1. Invocar VerifierEngine polimórficamente si está disponible
    if verifier is not None:
        verify_fn = getattr(verifier, "verify", None) or getattr(verifier, "verify_execution", None)
        if callable(verify_fn):
            try:
                call_with_state = True
                try:
                    sig = inspect.signature(verify_fn)
                    call_with_state = len(sig.parameters) > 0
                except (TypeError, ValueError):
                    call_with_state = True

                res = verify_fn(state) if call_with_state else verify_fn()
                v_res = await res if is_awaitable_or_coroutine(res) else res

                if isinstance(v_res, dict):
                    details.update(v_res)
                    if "status" in v_res:
                        raw_st = v_res["status"]
                        v_status = (
                            raw_st
                            if isinstance(raw_st, VerificationStatus)
                            else VerificationStatus(str(raw_st).lower())
                        )
                    elif "success" in v_res:
                        v_status = (
                            VerificationStatus.PASS if v_res["success"] else VerificationStatus.FAIL
                        )
                    elif "passed" in v_res:
                        v_status = (
                            VerificationStatus.PASS if v_res["passed"] else VerificationStatus.FAIL
                        )
                elif isinstance(v_res, VerificationStatus):
                    v_status = v_res
                elif isinstance(v_res, bool):
                    v_status = VerificationStatus.PASS if v_res else VerificationStatus.FAIL
                elif v_res is not None:
                    details["engine_output"] = str(v_res)

            except Exception as exc:
                logger.exception(
                    "Excepción durante la ejecución de VerifierEngine '%s': %s", verifier.name, exc
                )
                v_status = VerificationStatus.FAIL
                details["error"] = str(exc)
        else:
            logger.warning(
                "VerifierEngine '%s' no implementa método verify invocable.", verifier.name
            )
    else:
        details["fallback"] = True
        details["reason"] = (
            "Anomalías detectadas en registros de pasos previos."
            if (has_failed_records or has_fatal_errors)
            else "Comprobación básica autónoma superada."
        )

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    details["duration_ms"] = duration_ms

    is_failed = v_status in (VerificationStatus.FAIL, VerificationStatus.DEGRADED)

    # 2. Generación de traza de auditoría
    audit = AuditRecord(
        event_type="verification_failed" if is_failed else "verification_completed",
        actor=str(details.get("verified_by", "core")),
        details={
            "status": v_status.value,
            "details": details,
            "duration_ms": duration_ms,
        },
    )

    new_errors: list[ExecutionError] = []
    if is_failed:
        new_errors.append(
            ExecutionError(
                code="VERIFICATION_FAILED",
                message=str(
                    details.get("reason")
                    or details.get("error")
                    or "Anomalía post-ejecución detectada por VerifierEngine"
                ),
                component="verify",
                fatal=False,
            )
        )

    verification_entry = {
        "status": v_status.value,
        "timestamp": datetime.now(UTC).isoformat(),
        "details": details,
    }

    verifier_name = str(details.get("verified_by", "core"))
    cognitive_step = CognitiveStepRecord(
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
        details={
            "status": v_status.value,
            "verified_by": verifier_name,
            "details": details,
        },
        duration_ms=duration_ms,
        timestamp=datetime.now(UTC),
    )

    result_mutations: dict[str, Any] = {
        "status": AgentExecutionStatus.VERIFYING,
        "verification_results": [verification_entry],
        "cognitive_steps": [cognitive_step],
        "audit_trail": [audit],
    }

    if new_errors:
        result_mutations["errors"] = new_errors

    return result_mutations
