"""Enrutadores y endpoints de la API REST de jg_agente."""

from app.api.executions import router as executions_router
from app.api.telemetry import router as telemetry_router

__all__ = ["executions_router", "telemetry_router"]
