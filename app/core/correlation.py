# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo de contexto y propagación distribuida de Correlation-ID para jg_agente.

Proporciona almacenamiento seguro en contextvars, middleware ASGI para FastAPI
y filtros de logging para correlacionar trazas end-to-end con jg_dashboard.
"""

import logging
import uuid
from contextvars import ContextVar, Token

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Variable de contexto asíncrono para el correlation_id activo en la corrutina actual
_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Obtiene el correlation_id activo en el contexto actual."""
    return _correlation_id_ctx.get()


def set_correlation_id(correlation_id: str | None) -> Token[str | None]:
    """Establece un nuevo correlation_id en el contexto actual y retorna el token para reseteo."""
    return _correlation_id_ctx.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    """Restaura el correlation_id previo mediante su token de contexto."""
    _correlation_id_ctx.reset(token)


class CorrelationLogFilter(logging.Filter):
    """Filtro de logging que inyecta el correlation_id en cada registro de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        cid = get_correlation_id()
        record.correlation_id = f"[{cid}] " if cid else ""
        return True


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware FastAPI que extrae o genera X-Correlation-ID y lo propaga."""

    HEADER_NAME = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Extraer cabecera insensible a mayúsculas o generar un UUIDv4
        raw_cid = request.headers.get(self.HEADER_NAME) or request.headers.get("x-correlation-id")
        cid = raw_cid.strip() if raw_cid and raw_cid.strip() else str(uuid.uuid4())

        token = set_correlation_id(cid)
        request.state.correlation_id = cid

        try:
            response = await call_next(request)
            response.headers[self.HEADER_NAME] = cid
            return response
        finally:
            reset_correlation_id(token)
