# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Enrutadores y endpoints de la API REST de jg_agente."""

from app.api.executions import router as executions_router
from app.api.telemetry import router as telemetry_router
from app.api.tools import router as tools_router

__all__ = ["executions_router", "telemetry_router", "tools_router"]
