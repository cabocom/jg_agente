"""Servidor principal FastAPI de jg_agente (Execution Plane)."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app import __version__
from app.api import executions_router, telemetry_router
from app.core.boot import init_agent_capabilities
from app.core.config import settings

logger = logging.getLogger("jg_agente")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Ciclo de vida de la aplicación con validación de boot e inicialización de plugins."""
    logger.info(
        "Iniciando jg_agente v%s (Agent ID: %s, ENV: %s)",
        __version__,
        settings.AGENT_ID,
        settings.ENV,
    )

    # 1. Autodescubrimiento, validación de integridad de arranque y registro
    registry, plugin_manager = init_agent_capabilities(settings)
    app.state.registry = registry
    app.state.plugin_manager = plugin_manager

    # 2. Inicialización asíncrona de plugins
    await plugin_manager.startup()

    yield

    # 3. Apagado ordenado
    logger.info("Deteniendo jg_agente...")
    await plugin_manager.shutdown()


app = FastAPI(
    title="jg_agente",
    description="Motor Autónomo de Ejecución Cognitiva y Accionamiento (Execution Plane)",
    version=__version__,
    lifespan=lifespan,
)

# Montar enrutadores REST de la API
app.include_router(executions_router)
app.include_router(telemetry_router)


@app.get("/", tags=["Root"])
async def root() -> dict[str, Any]:
    """Endpoint raíz con metadatos del servicio."""
    return {
        "service": "jg_agente",
        "version": __version__,
        "agent_id": settings.AGENT_ID,
        "environment": settings.ENV,
        "status": "online",
    }
