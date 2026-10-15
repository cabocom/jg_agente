# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Endpoints REST de telemetría, salud y observabilidad de jg_agente."""

import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import settings
from app.core.registry import CapabilityRegistry
from app.db.models import CoreExecution
from app.db.session import get_async_session
from app.models.io import (
    ExecutionMetrics,
    HealthComponentStatus,
    HealthResponse,
    MetricsResponse,
)

logger = logging.getLogger("jg_agente.api.telemetry")

router = APIRouter(tags=["Telemetry", "Observability"])

_APP_START_TIME = time.time()


def get_app_registry(request: Request) -> CapabilityRegistry:
    """Obtiene el registro de capacidades activo desde app.state."""
    return getattr(request.app.state, "registry", None) or CapabilityRegistry()


@router.get(
    "/capabilities",
    status_code=status.HTTP_200_OK,
    summary="Catálogo de capacidades activas del agente",
    description="Devuelve el inventario de herramientas, motores cognitivos y plugins registrados en el Core.",
)
async def get_capabilities(
    registry: CapabilityRegistry = Depends(get_app_registry),
) -> dict[str, Any]:
    """Retorna el catálogo consolidado de capacidades y herramientas activas."""
    return registry.get_capabilities_summary()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
    summary="Chequeo de salud y conectividad de subsistemas",
    description="Verifica de forma asíncrona la conectividad con PostgreSQL, el checkpointer y la preparación del modelo cognitivo LLM.",
)
async def get_health(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
) -> HealthResponse:
    """Chequea la disponibilidad y latencia de PostgreSQL, el proveedor LLM y el checkpointer."""
    components: dict[str, HealthComponentStatus] = {}

    # 1. Comprobación de conectividad con PostgreSQL
    db_status = "disconnected"
    db_latency: float | None = None
    db_error: str | None = None
    t0 = time.perf_counter()
    try:
        from sqlalchemy import text

        res = await db.execute(text("SELECT 1"))
        _ = res.scalar()
        db_latency = round((time.perf_counter() - t0) * 1000.0, 2)
        db_status = "connected"
    except Exception as exc:
        db_status = "disconnected"
        db_error = str(exc)
        logger.warning("Fallo en healthcheck de PostgreSQL: %s", exc)

    components["database"] = HealthComponentStatus(
        status=db_status,
        latency_ms=db_latency,
        details={
            "host": settings.POSTGRES_HOST,
            "port": settings.POSTGRES_PORT,
            "database": settings.POSTGRES_DB,
        },
        error=db_error,
    )

    # 2. Comprobación del proveedor de LLM
    llm_provider = settings.LLM_PROVIDER
    llm_model = settings.LLM_MODEL
    components["llm"] = HealthComponentStatus(
        status="ready",
        details={
            "provider": llm_provider,
            "model": llm_model,
        },
    )

    # 3. Comprobación del checkpointer
    checkpointer_kind = getattr(settings, "CHECKPOINT_SAVER", "postgres")
    checkpointer_instance = getattr(request.app.state, "checkpointer", None)
    ckpt_status = "ready"
    ckpt_error: str | None = None

    if checkpointer_kind.lower() in ("postgres", "postgresql"):
        if getattr(checkpointer_instance, "is_degraded", False):
            ckpt_status = "degraded"
            ckpt_error = getattr(
                checkpointer_instance,
                "degraded_reason",
                "PostgresSaver no pudo conectar tras reintentos (degradado a memoria)",
            )
        elif checkpointer_instance is not None and not hasattr(checkpointer_instance, "conn"):
            # Si se configuró postgres pero la instancia activa no gestiona conexiones pool/postgres
            ckpt_status = "degraded"
            ckpt_error = "Checkpointer configurado como postgres pero operando en memoria"
        elif db_status == "disconnected":
            ckpt_status = "disconnected"
            ckpt_error = db_error or "PostgreSQL no responde"

    components["checkpointer"] = HealthComponentStatus(
        status=ckpt_status,
        details={
            "type": checkpointer_kind,
            "active_class": (
                type(checkpointer_instance).__name__ if checkpointer_instance else "None"
            ),
        },
        error=ckpt_error,
    )

    is_healthy = db_status == "connected" and ckpt_status in ("ready", "healthy")
    if is_healthy:
        global_status = "healthy"
    else:
        global_status = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=global_status,
        service="jg_agente",
        version=__version__,
        database=db_status,
        database_error=db_error,
        components=components,
        timestamp=datetime.now(UTC),
    )


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Métricas agregadas de rendimiento y ejecución",
    description="Devuelve estadísticas de ejecuciones (totales, tiempos promedio, mínimos, máximos) y conteos HITL.",
)
async def get_metrics(
    registry: CapabilityRegistry = Depends(get_app_registry),
    db: AsyncSession = Depends(get_async_session),
) -> MetricsResponse:
    """Calcula y agrega métricas cuantitativas desde la tabla core_executions."""
    uptime = round(time.time() - _APP_START_TIME, 2)
    exec_metrics = ExecutionMetrics()
    hitl_metrics: dict[str, int] = {
        "approvals_requested": 0,
        "approvals_pending": 0,
    }

    try:
        # Consulta de totales y tiempos agregados
        time_query = select(
            func.count(CoreExecution.execution_id).label("total"),
            func.coalesce(func.avg(CoreExecution.execution_time_ms), 0.0).label("avg_time"),
            func.coalesce(func.min(CoreExecution.execution_time_ms), 0.0).label("min_time"),
            func.coalesce(func.max(CoreExecution.execution_time_ms), 0.0).label("max_time"),
        )
        time_result = await db.execute(time_query)
        time_row = time_result.first()
        if time_row:
            exec_metrics.total_executions = int(time_row.total or 0)
            exec_metrics.avg_execution_time_ms = round(float(time_row.avg_time or 0.0), 2)
            exec_metrics.min_execution_time_ms = round(float(time_row.min_time or 0.0), 2)
            exec_metrics.max_execution_time_ms = round(float(time_row.max_time or 0.0), 2)

        # Consulta de conteos agrupados por estado
        status_query = select(
            CoreExecution.status,
            func.count(CoreExecution.execution_id),
        ).group_by(CoreExecution.status)
        status_res = await db.execute(status_query)
        for row in status_res.all():
            st, count = row[0], int(row[1])
            if st == "completed":
                exec_metrics.completed = count
            elif st == "failed":
                exec_metrics.failed = count
            elif st == "cancelled":
                exec_metrics.cancelled = count
            elif st == "waiting_approval":
                exec_metrics.waiting_approval = count
                hitl_metrics["approvals_pending"] += count
            elif st == "in_progress":
                exec_metrics.in_progress = count

        # Consulta de estadísticas HITL
        hitl_query = select(func.count(CoreExecution.execution_id)).where(
            (CoreExecution.requires_approval.is_(True))
            | (CoreExecution.pending_approval_id.isnot(None))
            | (CoreExecution.status == "waiting_approval")
        )
        hitl_res = await db.execute(hitl_query)
        hitl_count = hitl_res.scalar() or 0
        hitl_metrics["approvals_requested"] = int(hitl_count)

    except Exception as exc:
        logger.warning(
            "Fallo al consultar métricas de core_executions en base de datos: %s",
            exc,
        )

    # Conteos de capacidades registradas
    capabilities_count: dict[str, int] = {
        "tools_count": len(registry.list_tools()),
        "engines_count": len(registry.list_engines()),
        "plugins_count": len(registry.list_plugins()),
    }

    return MetricsResponse(
        service="jg_agente",
        version=__version__,
        uptime_seconds=uptime,
        executions=exec_metrics,
        capabilities=capabilities_count,
        hitl=hitl_metrics,
        timestamp=datetime.now(UTC),
    )
