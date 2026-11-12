# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Evaluación de estados y construcción de payload de salida en el nodo conclude."""

from typing import Any

from app.core.async_compat import ensure_awaited, is_awaitable_or_coroutine
from app.models.io import ExecutionStatus
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalStatus,
    GoalStatus,
    StepStatus,
    VerificationStatus,
)


def evaluate_final_statuses(
    state: AgentState,
    records: list[Any],
    errors: list[Any],
) -> tuple[bool, bool, bool, bool, bool, AgentExecutionStatus, ExecutionStatus, Any]:
    """Evalúa los estados lógicos de conclusión (cancelado, fallido, límite alcanzado, resuelto)."""
    v_results = list(state.get("verification_results") or [])
    has_verification_fail = any(
        (v.get("status") if isinstance(v, dict) else getattr(v, "status", None))
        in (
            VerificationStatus.FAIL,
            VerificationStatus.FAIL.value,
            VerificationStatus.DEGRADED,
            VerificationStatus.DEGRADED.value,
        )
        for v in v_results
    )
    has_failed_records = any(getattr(r, "status", None) == StepStatus.FAILED for r in records)
    has_fatal_errors = any(getattr(e, "fatal", False) for e in errors)

    approval_val = state.get("approval")
    is_rejected = False
    if approval_val is not None:
        appr_status = getattr(approval_val, "status", None) or (
            approval_val.get("status") if isinstance(approval_val, dict) else None
        )
        is_rejected = appr_status in (
            ApprovalStatus.REJECTED,
            ApprovalStatus.REJECTED.value,
            "rejected",
        )

    is_cancelled = (
        state.get("status")
        in (AgentExecutionStatus.CANCELLED, AgentExecutionStatus.CANCELLED.value, "cancelled")
        or is_rejected
    )

    is_failed = (
        has_failed_records
        or has_fatal_errors
        or has_verification_fail
        or state.get("status") in (AgentExecutionStatus.FAILED, AgentExecutionStatus.ROLLING_BACK)
    )

    eval_records = list(state.get("evaluation_records") or [])
    last_eval = eval_records[-1] if eval_records else None
    goal_status = getattr(last_eval, "goal_status", None) if last_eval else None
    if goal_status is None and isinstance(last_eval, dict):
        goal_status = last_eval.get("goal_status")
    status_val = (
        goal_status.value
        if isinstance(goal_status, GoalStatus)
        else str(goal_status or "").lower().strip()
    )

    curr_iteration = int(state.get("iteration", 1))
    max_iterations = int(state.get("max_iterations", 3))
    is_limit_reached = curr_iteration >= max_iterations and status_val in (
        GoalStatus.NEEDS_MORE_INFO.value,
        "needs_more_info",
    )

    if is_cancelled:
        final_agent_status = AgentExecutionStatus.FAILED
        final_output_status = ExecutionStatus.CANCELLED
        is_resolved = False
    elif is_failed:
        final_agent_status = AgentExecutionStatus.FAILED
        final_output_status = ExecutionStatus.FAILED
        is_resolved = False
    elif is_limit_reached:
        final_agent_status = AgentExecutionStatus.FAILED
        final_output_status = ExecutionStatus.COMPLETED
        is_resolved = False
    else:
        final_agent_status = AgentExecutionStatus.RESOLVED
        final_output_status = ExecutionStatus.COMPLETED
        is_resolved = True

    return (
        is_cancelled,
        is_rejected,
        is_failed,
        is_resolved,
        is_limit_reached,
        final_agent_status,
        final_output_status,
        last_eval,
    )


async def build_data_payload(
    records: list[Any],
    cog_steps: list[Any],
    state: AgentState,
) -> dict[str, Any]:
    """Serializa registros de ejecución, pasos cognitivos y snapshots para AgentOutput.data."""
    data_payload: dict[str, Any] = {}
    if records:
        data_payload["steps_count"] = len(records)
        serialized_records = []
        for r in records:
            if hasattr(r, "output") and is_awaitable_or_coroutine(r.output):
                try:
                    r.output = await ensure_awaited(r.output)
                except Exception:
                    r.output = str(r.output)
            serialized_records.append(
                r.model_dump(mode="json") if hasattr(r, "model_dump") else dict(r)
            )
        data_payload["execution_records"] = serialized_records

    data_payload["cognitive_steps"] = [
        s.model_dump(mode="json") if hasattr(s, "model_dump") else dict(s) for s in cog_steps
    ]
    data_payload["steps"] = data_payload["cognitive_steps"]

    for key in ("environment_snapshot", "verification_results", "rollback_records"):
        val = state.get(key)
        if val:
            data_payload[key] = val

    return data_payload
