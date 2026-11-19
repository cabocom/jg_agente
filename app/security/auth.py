# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo de autenticación y verificación de firmas criptográficas HMAC para jg_agente.

Implementa el contrato criptográfico canónico compartido con jg_dashboard (GLOBAL-001 / ISSUE-AGENT-001):
canonical_string = f"{METHOD}\\n{PATH}\\n{TIMESTAMP}\\n{SHA256(RAW_BODY)}"
signature = HMAC-SHA256(canonical_string, secret).hexdigest()
"""

import logging
import re
import threading
import time

from fastapi import HTTPException, Request, status
from jg_sdk.auth import (
    DEFAULT_MAX_TIMESTAMP_SKEW_SECONDS,
    compute_body_sha256,
    compute_canonical_string,
    compute_hmac_signature,
    verify_hmac_signature,
)

from app.core.config import settings

logger = logging.getLogger("jg_agente.security.auth")

# Ventana máxima de tolerancia temporal contra ataques de repetición (5 minutos)
MAX_TIMESTAMP_SKEW_SECONDS = DEFAULT_MAX_TIMESTAMP_SKEW_SECONDS

# Un timestamp futuro (+skew) sigue siendo válido hasta +2*skew: el nonce debe cubrir toda esa ventana
NONCE_TTL_SECONDS = MAX_TIMESTAMP_SKEW_SECONDS * 2
_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")
_NONCE_CACHE_MAX_ENTRIES = 100_000


class NonceReplayCache:
    """Caché TTL thread-safe de nonces de un solo uso (anti-replay).

    Es local al proceso: con varios workers/réplicas cada uno mantiene su propia caché, por lo que
    un despliegue multi-réplica debe sustituirla por un almacén compartido (p. ej. Redis SET NX EX).
    """

    def __init__(self, max_entries: int = _NONCE_CACHE_MAX_ENTRIES) -> None:
        self._entries: dict[str, float] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def register(self, key: str, ttl_seconds: float, now: float | None = None) -> bool:
        """Registra la clave. Devuelve False si ya existía y seguía vigente (replay)."""
        current = time.monotonic() if now is None else now
        with self._lock:
            expiry = self._entries.get(key)
            if expiry is not None and expiry > current:
                return False
            if len(self._entries) >= self._max_entries:
                self._entries = {k: e for k, e in self._entries.items() if e > current}
            self._entries[key] = current + ttl_seconds
            return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_nonce_cache = NonceReplayCache()


def get_nonce_cache() -> NonceReplayCache:
    """Devuelve la caché de nonces del proceso (inyectable/limpiable en tests)."""
    return _nonce_cache


def _extract_and_validate_headers(request: Request) -> tuple[str, str, str, str]:
    """Valida la presencia y formato de las cabeceras de autenticación requeridas."""
    sig_header = request.headers.get("X-Signature")
    ts_header = request.headers.get("X-Timestamp")
    agent_id_header = request.headers.get("X-Agent-ID")
    nonce_header = (request.headers.get("X-Nonce") or "").strip()

    if not sig_header or not ts_header or not agent_id_header:
        missing = [
            h
            for h, v in [
                ("X-Signature", sig_header),
                ("X-Timestamp", ts_header),
                ("X-Agent-ID", agent_id_header),
            ]
            if not v
        ]
        logger.warning(
            "Faltan cabeceras de autenticación en %s: %s", request.url.path, ", ".join(missing)
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Cabeceras de autenticación requeridas ausentes: {', '.join(missing)}",
        )
    if not nonce_header and settings.HMAC_REQUIRE_NONCE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabecera de autenticación requerida ausente: X-Nonce",
        )
    if nonce_header and not _NONCE_PATTERN.fullmatch(nonce_header):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato de X-Nonce inválido.",
        )
    return sig_header, ts_header, agent_id_header.strip(), nonce_header


def _validate_timestamp_skew(ts_header: str) -> None:
    """Valida que el timestamp sea numérico y se encuentre dentro de la ventana de tolerancia."""
    try:
        req_timestamp = int(ts_header.strip())
    except ValueError as err:
        logger.warning("Cabecera X-Timestamp inválida (no numérico): %s", ts_header)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabecera X-Timestamp inválida: debe ser un entero epoch UNIX.",
        ) from err
    current_time = int(time.time())
    diff = abs(current_time - req_timestamp)
    if diff > MAX_TIMESTAMP_SKEW_SECONDS:
        logger.warning(
            "Timestamp expirado: recibido=%d, actual=%d, diff=%ds",
            req_timestamp,
            current_time,
            diff,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Timestamp fuera de la ventana de tolerancia anti-replay permitida ({MAX_TIMESTAMP_SKEW_SECONDS}s).",
        )


def _resolve_agent_credentials(request: Request, agent_id_header: str) -> str:
    """Resuelve el secreto esperado y valida que la petición esté dirigida a este agente."""
    app_creds = getattr(request.app.state, "credentials", None)
    expected_id = getattr(app_creds, "agent_id", None) or settings.AGENT_ID
    expected_secret = (
        getattr(app_creds, "permanent_secret", None) or settings.PERMANENT_AGENT_SECRET
    )

    if not expected_secret:
        logger.error("El agente no tiene configurado un secreto permanente.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agente no inicializado con credenciales de autenticación.",
        )
    if agent_id_header != expected_id.strip():
        logger.warning("X-Agent-ID '%s' no coincide con local '%s'", agent_id_header, expected_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"X-Agent-ID '{agent_id_header}' no coincide con el agente destinatario.",
        )
    return expected_secret


async def verify_control_plane_auth(request: Request) -> None:
    """Dependencia FastAPI que autentica que la petición provenga del Control Plane (jg_dashboard)."""
    sig, ts, agent_id, nonce = _extract_and_validate_headers(request)
    _validate_timestamp_skew(ts)
    expected_secret = _resolve_agent_credentials(request, agent_id)

    body_bytes = await request.body()
    canonical = compute_canonical_string(
        method=request.method,
        path=request.url.path,
        timestamp=ts,
        body_bytes=body_bytes,
        nonce=nonce or None,
    )
    if not verify_hmac_signature(expected_secret, canonical, sig):
        logger.warning("Firma criptográfica inválida para %s %s", request.method, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firma criptográfica HMAC inválida o cuerpo alterado.",
        )
    if nonce and not get_nonce_cache().register(f"{agent_id}:{nonce}", NONCE_TTL_SECONDS):
        logger.warning("Nonce reutilizado en %s %s", request.method, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nonce replayed",
        )
    logger.debug(
        "Petición autenticada exitosamente con HMAC para %s %s", request.method, request.url.path
    )


__all__ = [
    "DEFAULT_MAX_TIMESTAMP_SKEW_SECONDS",
    "MAX_TIMESTAMP_SKEW_SECONDS",
    "NONCE_TTL_SECONDS",
    "NonceReplayCache",
    "compute_body_sha256",
    "compute_canonical_string",
    "compute_hmac_signature",
    "get_nonce_cache",
    "verify_control_plane_auth",
    "verify_hmac_signature",
]
