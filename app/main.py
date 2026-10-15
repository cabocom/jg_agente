# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servidor principal FastAPI de jg_agente (Execution Plane)."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app import __version__
from app.api import executions_router, telemetry_router
from app.core.boot import init_agent_capabilities
from app.core.checkpointer import close_checkpointer, get_checkpointer
from app.core.config import settings
from app.core.correlation import CorrelationIdMiddleware, CorrelationLogFilter
from app.core.heartbeat import HeartbeatService
from app.core.registration import auto_register_agent
from app.security import (
    get_security_audit_logger,
    get_security_guard,
    get_ssrf_validator,
)

logger = logging.getLogger("jg_agente")
correlation_filter = CorrelationLogFilter()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(correlation_id)s%(message)s",
)
for handler in logging.root.handlers:
    handler.addFilter(correlation_filter)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Ciclo de vida de la aplicación con validación de boot, registro, heartbeat y plugins."""
    logger.info(
        "Iniciando jg_agente v%s (Agent ID: %s, ENV: %s)",
        __version__,
        settings.AGENT_ID,
        settings.ENV,
    )

    # 0. Pre-inicialización determinista de singletons de seguridad (AGENTE-CONC-01)
    get_security_audit_logger()
    get_ssrf_validator()
    get_security_guard()

    # 1. Autodescubrimiento, validación de integridad de arranque y registro
    registry, plugin_manager = init_agent_capabilities(settings)
    app.state.registry = registry
    app.state.plugin_manager = plugin_manager

    # 2. Inicialización y precalentamiento del checkpointer para LangGraph
    app.state.checkpointer = get_checkpointer()

    # 3. Inicialización asíncrona de plugins
    await plugin_manager.startup()

    # 4. Comprobación de credenciales y aprovisionamiento con Dashboard (Zero-Trust Bootstrap)
    credentials = await auto_register_agent(settings=settings, registry=registry)
    app.state.credentials = credentials
    app.state.credentials_verified = credentials.verified if credentials else False

    # 5. Iniciar servicio de heartbeat periódico en segundo plano si está habilitado y autenticado
    heartbeat_service: HeartbeatService | None = None
    if settings.ENABLE_HEARTBEAT and credentials is not None:
        heartbeat_service = HeartbeatService(settings=settings, registry=registry)
        heartbeat_service.start()
    app.state.heartbeat_service = heartbeat_service

    yield

    # 6. Apagado ordenado y liberación de recursos
    logger.info("Deteniendo jg_agente...")
    if heartbeat_service is not None:
        await heartbeat_service.stop()
    await plugin_manager.shutdown()
    close_checkpointer(getattr(app.state, "checkpointer", None))


app = FastAPI(
    title="jg_agente",
    description="Motor Autónomo de Ejecución Cognitiva y Accionamiento (Execution Plane)",
    version=__version__,
    lifespan=lifespan,
)

# Middleware para inyección y propagación de X-Correlation-ID
app.add_middleware(CorrelationIdMiddleware)

# Montar enrutadores REST de la API
app.include_router(executions_router)
app.include_router(telemetry_router)


@app.get("/", tags=["Root"])
async def root() -> dict[str, Any]:
    """Endpoint raíz con metadatos del servicio."""
    is_registered = bool(settings.PERMANENT_AGENT_SECRET)
    is_verified = getattr(app.state, "credentials_verified", False)
    hb_service: HeartbeatService | None = getattr(app.state, "heartbeat_service", None)
    return {
        "service": "jg_agente",
        "version": __version__,
        "agent_id": settings.AGENT_ID,
        "environment": settings.ENV,
        "status": "online",
        "registered": is_registered,
        "credentials_verified": is_verified,
        "dashboard_url": settings.DASHBOARD_URL,
        "heartbeat_active": hb_service.is_running if hb_service is not None else False,
        "last_heartbeat_at": (
            hb_service.last_successful_heartbeat if hb_service is not None else None
        ),
    }
