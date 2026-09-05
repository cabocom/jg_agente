"""Servidor principal FastAPI de jg_agente (Execution Plane)."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import __version__
from app.api.executions import router as executions_router
from app.core.boot import init_agent_capabilities
from app.core.config import settings
from app.core.registry import CapabilityRegistry

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


@app.get("/capabilities", tags=["Observability"])
async def capabilities(request: Request) -> dict[str, Any]:
    """Catálogo consolidado de herramientas, motores y plugins registrados en jg_agente."""
    registry: CapabilityRegistry = (
        getattr(request.app.state, "registry", None) or CapabilityRegistry()
    )
    return registry.get_capabilities_summary()


@app.get("/health", tags=["Observability"])
async def health(response: Response) -> dict[str, Any]:
    """Chequeo de salud del agente y conectividad con PostgreSQL."""
    db_status = "untested"
    db_error = None

    try:
        engine = create_async_engine(
            settings.async_database_url,
            pool_pre_ping=True,
            connect_args={"timeout": 3},
        )
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        db_status = "connected"
    except Exception as exc:
        db_status = "disconnected"
        db_error = str(exc)
        logger.warning("Fallo en verificación de base de datos en /health: %s", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": "jg_agente",
        "version": __version__,
        "database": db_status,
        "database_error": db_error,
    }
