# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo de autenticación y verificación de firmas criptográficas HMAC para jg_agente.

Implementa el contrato criptográfico canónico compartido con jg_dashboard (GLOBAL-001 / ISSUE-AGENT-001):
canonical_string = f"{METHOD}\\n{PATH}\\n{TIMESTAMP}\\n{SHA256(RAW_BODY)}"
signature = HMAC-SHA256(canonical_string, secret).hexdigest()
"""

import hashlib
import hmac
import logging
import re
import threading
import time

from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger("jg_agente.security.auth")

# Ventana máxima de tolerancia temporal contra ataques de repetición (5 minutos)
MAX_TIMESTAMP_SKEW_SECONDS = 300

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


def compute_body_sha256(body_bytes: bytes | None) -> str:
    """Calcula el hash SHA-256 en hexadecimal del cuerpo crudo en minúsculas.

    Para cuerpos vacíos o None, devuelve el hash estándar de b"".
    """
    data = body_bytes or b""
    return hashlib.sha256(data).hexdigest()


def compute_canonical_string(
    method: str,
    path: str,
    timestamp: str | int,
    body_bytes: bytes | None,
    nonce: str | None = None,
) -> str:
    """Construye la cadena canónica normalizada para la firma.

    Formato:
        METHOD\\nPATH\\nTIMESTAMP\\nBODY_SHA256[\\nNONCE]

    El nonce (opcional) forma parte del material firmado: no puede eliminarse ni sustituirse.
    """
    norm_method = method.strip().upper()
    norm_path = path.strip()
    norm_timestamp = str(timestamp).strip()
    body_hash = compute_body_sha256(body_bytes)

    canonical = f"{norm_method}\n{norm_path}\n{norm_timestamp}\n{body_hash}"
    if nonce:
        canonical += f"\n{nonce.strip()}"
    return canonical


def compute_hmac_signature(secret: str, canonical_string: str) -> str:
    """Calcula la firma HMAC-SHA256 en formato hexadecimal."""
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=canonical_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_hmac_signature(secret: str, canonical_string: str, received_signature: str) -> bool:
    """Verifica en tiempo constante que la firma recibida coincida con la calculada."""
    expected_signature = compute_hmac_signature(secret, canonical_string)
    return hmac.compare_digest(expected_signature.lower(), received_signature.strip().lower())


async def verify_control_plane_auth(request: Request) -> None:
    """Dependencia FastAPI que autentica que la petición provenga del Control Plane (jg_dashboard).

    Valida cabeceras X-Signature, X-Timestamp y X-Agent-ID, comprueba la ventana anti-replay
    y verifica la firma HMAC-SHA256 contra el secreto permanente del agente.

    Raises:
        HTTPException(401): Si falta alguna cabecera, el timestamp expiró, el Agent ID no coincide
                            o la firma criptográfica es inválida.
    """
    sig_header = request.headers.get("X-Signature")
    ts_header = request.headers.get("X-Timestamp")
    agent_id_header = request.headers.get("X-Agent-ID")
    nonce_header = (request.headers.get("X-Nonce") or "").strip()

    # 1. Validar presencia de cabeceras obligatorias
    if not sig_header or not ts_header or not agent_id_header:
        missing = []
        if not sig_header:
            missing.append("X-Signature")
        if not ts_header:
            missing.append("X-Timestamp")
        if not agent_id_header:
            missing.append("X-Agent-ID")
        logger.warning(
            "Rechazada petición a %s: Faltan cabeceras de autenticación: %s",
            request.url.path,
            ", ".join(missing),
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

    # 2. Validar timestamp numérico y ventana anti-replay
    try:
        req_timestamp = int(ts_header.strip())
    except ValueError as err:
        logger.warning("Cabecera X-Timestamp inválida (no numérico): %s", ts_header)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabecera X-Timestamp inválida: debe ser un entero epoch UNIX.",
        ) from err

    current_time = int(time.time())
    if abs(current_time - req_timestamp) > MAX_TIMESTAMP_SKEW_SECONDS:
        logger.warning(
            "Timestamp expirado o fuera de skew: recibido=%d, actual=%d, diff=%d seg (máx %d seg)",
            req_timestamp,
            current_time,
            abs(current_time - req_timestamp),
            MAX_TIMESTAMP_SKEW_SECONDS,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Timestamp fuera de la ventana de tolerancia anti-replay permitida ({MAX_TIMESTAMP_SKEW_SECONDS}s).",
        )

    # 3. Resolver identidad y secreto esperado del agente
    app_creds = getattr(request.app.state, "credentials", None)
    expected_agent_id = getattr(app_creds, "agent_id", None) or settings.AGENT_ID
    expected_secret = (
        getattr(app_creds, "permanent_secret", None) or settings.PERMANENT_AGENT_SECRET
    )

    if not expected_secret:
        logger.error(
            "El agente no tiene configurado un secreto permanente (PERMANENT_AGENT_SECRET ni credentials). Rechazando petición."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agente no inicializado con credenciales de autenticación.",
        )

    # 4. Validar que la petición va dirigida a este agente
    if agent_id_header.strip() != expected_agent_id.strip():
        logger.warning(
            "X-Agent-ID '%s' no coincide con el identificador del agente local '%s'",
            agent_id_header,
            expected_agent_id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"X-Agent-ID '{agent_id_header}' no coincide con el agente destinatario.",
        )

    # 5. Obtener el cuerpo crudo y construir la cadena canónica
    # En FastAPI / Starlette, request.body() cachea los bytes internamente permitiendo lecturas posteriores
    body_bytes = await request.body()
    canonical_string = compute_canonical_string(
        method=request.method,
        path=request.url.path,
        timestamp=ts_header,
        body_bytes=body_bytes,
        nonce=nonce_header or None,
    )

    # 6. Comprobar firma HMAC-SHA256
    if not verify_hmac_signature(expected_secret, canonical_string, sig_header):
        logger.warning(
            "Firma criptográfica inválida para %s %s desde %s",
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firma criptográfica HMAC inválida o cuerpo alterado.",
        )

    # 7. Anti-replay: nonce de un solo uso, registrado SOLO tras validar la firma para que un
    # atacante sin secreto no pueda "quemar" nonces legítimos.
    if nonce_header and not get_nonce_cache().register(
        f"{agent_id_header.strip()}:{nonce_header}", NONCE_TTL_SECONDS
    ):
        logger.warning(
            "Nonce reutilizado (replay) en %s %s desde %s",
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nonce replayed",
        )

    logger.debug(
        "Petición autenticada exitosamente con HMAC para %s %s",
        request.method,
        request.url.path,
    )
