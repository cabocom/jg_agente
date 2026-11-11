# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de consulta y armonización de estado de ejecuciones cognitivas."""

import logging
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.db.models import CoreExecution
from app.models.io import ExecutionStatus, ExecutionThreadDetail
from app.models.state import AgentExecutionStatus, ApprovalStatus

logger = logging.getLogger("jg_agente.services.query")


def _extract_plan_dict(vals: dict[str, Any]) -> dict[str, Any] | None:
    """Extrae y normaliza el plan cognitivo si existe en el estado."""
    plan_obj = vals.get("plan")
    if plan_obj is not None:
        if hasattr(plan_obj, "model_dump"):
            return cast(dict[str, Any], plan_obj.model_dump(mode="json"))
        if isinstance(plan_obj, dict):
            return plan_obj
    return None


def _extract_steps(
    vals: dict[str, Any],
    db_record: CoreExecution | None,
    status_val: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extrae y armoniza las listas de pasos cognitivos y registros de ejecución."""
    raw_cog = vals.get("cognitive_steps")
    if not raw_cog and db_record and isinstance(db_record.data, dict):
        raw_cog = db_record.data.get("cognitive_steps")

    cog_steps: list[dict[str, Any]] = []
    for rec in raw_cog or []:
        item = (
            rec.model_dump(mode="json")
            if hasattr(rec, "model_dump")
            else (dict(rec) if isinstance(rec, dict) else {"raw": str(rec)})
        )
        if (
            status_val != ExecutionStatus.WAITING_APPROVAL.value
            and item.get("status") == "waiting_approval"
        ):
            item["status"] = (
                "failed" if status_val == ExecutionStatus.CANCELLED.value else "completed"
            )
        cog_steps.append(item)

    raw_exec = vals.get("execution_records")
    if not raw_exec and db_record and isinstance(db_record.data, dict):
        raw_exec = db_record.data.get("execution_records")

    exec_steps: list[dict[str, Any]] = []
    for rec in raw_exec or []:
        exec_steps.append(
            rec.model_dump(mode="json")
            if hasattr(rec, "model_dump")
            else (rec if isinstance(rec, dict) else {"raw": str(rec)})
        )

    return cog_steps, cog_steps if cog_steps else exec_steps


def _extract_status_and_approval(
    vals: dict[str, Any],
    next_nodes: list[str],
    db_record: CoreExecution | None,
) -> tuple[str, str | None, bool, str | None]:
    """Armoniza el estado operacional y las banderas de gobernanza HITL."""
    raw_status = vals.get("status")
    if next_nodes and ("human_approval" in next_nodes or "risk_assess" in next_nodes):
        status_val: str = ExecutionStatus.WAITING_APPROVAL.value
    elif raw_status:
        status_val = raw_status.value if hasattr(raw_status, "value") else str(raw_status)
        if status_val == AgentExecutionStatus.RESOLVED.value:
            status_val = ExecutionStatus.COMPLETED.value
        elif status_val == AgentExecutionStatus.AWAITING_APPROVAL.value:
            status_val = ExecutionStatus.WAITING_APPROVAL.value
    elif db_record:
        status_val = db_record.status
    else:
        status_val = ExecutionStatus.IN_PROGRESS.value

    appr_obj = vals.get("approval")
    approval_status_val: str | None = None
    if appr_obj is not None:
        if hasattr(appr_obj, "status"):
            approval_status_val = (
                appr_obj.status.value if hasattr(appr_obj.status, "value") else str(appr_obj.status)
            )
        elif isinstance(appr_obj, dict) and appr_obj.get("status"):
            approval_status_val = str(appr_obj["status"])
    elif status_val == ExecutionStatus.WAITING_APPROVAL.value:
        approval_status_val = ApprovalStatus.PENDING.value

    requires_approval: bool = bool(
        vals.get("requires_approval")
        or vals.get("human_intervention_required")
        or (next_nodes and "human_approval" in next_nodes)
        or (db_record and db_record.requires_approval)
    )

    pending_approval_id: str | None = (
        str(vals.get("pending_approval_id"))
        if vals.get("pending_approval_id")
        else (db_record.pending_approval_id if db_record else None)
    )
    if requires_approval and not pending_approval_id:
        pending_approval_id = "human_approval_required"

    return status_val, approval_status_val, requires_approval, pending_approval_id


def _extract_errors(vals: dict[str, Any], db_record: CoreExecution | None) -> list[dict[str, Any]]:
    """Extrae y normaliza el historial de errores registrados."""
    raw_errors = vals.get("errors") or []
    errors_list: list[dict[str, Any]] = []
    for err in raw_errors:
        if hasattr(err, "model_dump"):
            errors_list.append(err.model_dump(mode="json"))
        elif isinstance(err, dict):
            errors_list.append(err)
        else:
            errors_list.append({"message": str(err)})
    if not errors_list and db_record and db_record.error:
        errors_list.append({"message": db_record.error, "code": "DB_RECORD_ERROR"})
    return errors_list


async def get_execution_thread_detail(
    thread_id: str,
    graph: Any,
    db: AsyncSession,
) -> ExecutionThreadDetail:
    """Recupera el detalle completo de un hilo de ejecución combinando checkpointer y BD."""
    state_snapshot: Any = None
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state_snapshot = await graph.aget_state(config)
    except Exception as exc:
        logger.warning(
            "No se pudo consultar checkpointer para thread '%s': %s",
            thread_id,
            exc,
        )

    db_record: CoreExecution | None = None
    try:
        query = (
            select(CoreExecution)
            .where(CoreExecution.thread_id == thread_id)
            .order_by(CoreExecution.created_at.desc())
        )
        res = await db.execute(query)
        db_record = res.scalars().first()
    except Exception as db_err:
        logger.warning(
            "No se pudo consultar registro en core_executions para thread '%s': %s",
            thread_id,
            db_err,
        )

    has_checkpoint = state_snapshot is not None and bool(getattr(state_snapshot, "values", None))
    if not has_checkpoint and db_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hilo de ejecución '{thread_id}' no encontrado.",
        )

    vals: dict[str, Any] = state_snapshot.values if has_checkpoint else {}
    req_obj = vals.get("request")
    out_obj = vals.get("output")
    next_nodes: list[str] = (
        list(state_snapshot.next)
        if state_snapshot and getattr(state_snapshot, "next", None)
        else []
    )

    status_val, appr_status, req_appr, pending_appr = _extract_status_and_approval(
        vals, next_nodes, db_record
    )
    cog_steps, steps_list = _extract_steps(vals, db_record, status_val)
    errors_list = _extract_errors(vals, db_record)

    execution_id = (
        getattr(req_obj, "execution_id", None)
        or (req_obj.get("execution_id") if isinstance(req_obj, dict) else None)
        or (db_record.execution_id if db_record else None)
    )
    prompt = (
        getattr(req_obj, "prompt", None)
        or (req_obj.get("prompt") if isinstance(req_obj, dict) else None)
        or (db_record.prompt if db_record else None)
    )
    response_text = (
        getattr(out_obj, "response", None)
        or (out_obj.get("response") if isinstance(out_obj, dict) else None)
        or (db_record.response if db_record else None)
    )

    metadata: dict[str, Any] = (
        dict(db_record.metadata_) if (db_record and db_record.metadata_) else {}
    )
    if req_obj and hasattr(req_obj, "metadata") and isinstance(req_obj.metadata, dict):
        metadata.update(req_obj.metadata)
    elif isinstance(req_obj, dict) and isinstance(req_obj.get("metadata"), dict):
        metadata.update(req_obj["metadata"])

    checkpoint_id: str | None = None
    if state_snapshot and getattr(state_snapshot, "config", None):
        cfg = state_snapshot.config.get("configurable", {})
        checkpoint_id = cfg.get("checkpoint_id")

    req_cid = getattr(req_obj, "correlation_id", None) if req_obj is not None else None
    cid = (
        vals.get("correlation_id")
        or req_cid
        or metadata.get("correlation_id")
        or get_correlation_id()
    )

    return ExecutionThreadDetail(
        thread_id=thread_id,
        execution_id=str(execution_id) if execution_id else None,
        correlation_id=cid,
        status=status_val,
        prompt=str(prompt) if prompt else None,
        response=str(response_text) if response_text else None,
        current_step=int(vals.get("current_step", len(steps_list))),
        next_nodes=next_nodes,
        plan=_extract_plan_dict(vals),
        steps=steps_list,
        cognitive_steps=cog_steps,
        approval_status=appr_status,
        requires_approval=req_appr,
        pending_approval_id=pending_appr,
        errors=errors_list,
        checkpoint_id=checkpoint_id,
        metadata=metadata,
        created_at=db_record.created_at if db_record else getattr(req_obj, "created_at", None),
        completed_at=db_record.completed_at
        if db_record
        else getattr(out_obj, "completed_at", None),
    )
