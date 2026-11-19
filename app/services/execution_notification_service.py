# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de emisión y reintento de webhooks asíncronos para notificar finalizaciones."""

import asyncio
import json
import logging
import secrets
import time
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from fastapi.encoders import jsonable_encoder

from app import __version__
from app.core.config import settings
from app.core.correlation import get_correlation_id
from app.models.io import AgentOutput
from app.security.auth import compute_canonical_string, compute_hmac_signature
from app.security.ip_policy import SSRFValidationError
from app.security.ssrf_validator import get_ssrf_validator

logger = logging.getLogger("jg_agente.services.notification")


def get_agent_credentials() -> tuple[str, str | None]:
    """Obtiene el identificador y secreto del agente para autenticación."""
    agent_id = settings.AGENT_ID
    secret = settings.PERMANENT_AGENT_SECRET
    if not secret:
        from app.core.registration import CredentialStore

        creds = CredentialStore.load(settings.CREDENTIALS_FILE)
        if creds:
            agent_id = creds.agent_id or agent_id
            secret = creds.permanent_secret or secret
    return agent_id, secret


def _build_notification_headers(
    agent_id: str,
    secret: str | None,
    cid: str,
    method: str = "POST",
    path: str = "",
    body_bytes: bytes = b"",
) -> dict[str, str]:
    """Construye las cabeceras HTTP de autenticación HMAC y trazabilidad para el webhook."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"jg_agente/{__version__}",
        "X-Correlation-ID": cid,
    }
    if agent_id:
        headers["X-Agent-ID"] = agent_id
    if secret:
        timestamp = int(time.time())
        nonce = secrets.token_hex(16)
        canonical = compute_canonical_string(method, path, timestamp, body_bytes, nonce=nonce)
        headers["X-Timestamp"] = str(timestamp)
        headers["X-Nonce"] = nonce
        headers["X-Signature"] = compute_hmac_signature(secret, canonical)
    return headers


def _build_notification_payload(output: AgentOutput, cid: str) -> dict[str, Any]:
    """Construye el payload JSON serializable para la notificación."""
    status_str = output.status.value if hasattr(output.status, "value") else str(output.status)
    payload = {
        "execution_id": output.execution_id,
        "thread_id": output.thread_id,
        "correlation_id": cid,
        "status": status_str,
        "response": output.response,
        "output": output.response,
        "data": output.data,
        "execution_time_ms": output.execution_time_ms,
        "requires_approval": output.requires_approval,
        "pending_approval_id": output.pending_approval_id,
        "metadata": output.metadata,
        "completed_at": (
            output.completed_at.isoformat()
            if output.completed_at
            else datetime.now(UTC).isoformat()
        ),
    }
    return cast(dict[str, Any], jsonable_encoder(payload))


async def _dispatch_webhook_http(
    target_url: str,
    fallback_url: str | None,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    agent_id: str = "",
    secret: str | None = None,
    cid: str = "",
    body_bytes: bytes = b"",
) -> tuple[bool, bool, int, str]:
    """Ejecuta la llamada HTTP del webhook retornando (éxito, terminal_error, status_code, texto)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(target_url, json=payload, headers=headers)
        if resp.status_code == 404 and fallback_url and target_url != fallback_url:
            fb_headers = dict(headers)
            if secret:
                fb_path = urlparse(fallback_url).path
                fb_headers = _build_notification_headers(
                    agent_id, secret, cid, "POST", fb_path, body_bytes
                )
            resp = await client.post(fallback_url, json=payload, headers=fb_headers)

        if resp.is_success:
            return True, False, resp.status_code, resp.text
        if 400 <= resp.status_code < 500:
            return False, True, resp.status_code, resp.text
        return False, False, resp.status_code, resp.text


async def notify_execution_completion(
    output: AgentOutput,
    callback_url: str | None = None,
) -> bool:
    """Envía notificación webhook hacia el Dashboard o URL de callback validando contra SSRF."""
    if callback_url:
        validator = get_ssrf_validator()
        try:
            validator.assert_safe_url(callback_url)
        except SSRFValidationError as exc:
            logger.error(
                "Webhook callback_url '%s' rechazado por política SSRF: %s",
                callback_url,
                exc,
            )
            return False

    target_url = (
        callback_url
        or f"{settings.DASHBOARD_URL.rstrip('/')}/api/v1/internal/executions/{output.execution_id}/complete"
    )
    fallback_url = (
        f"{settings.DASHBOARD_URL.rstrip('/')}/api/internal/executions/{output.execution_id}/complete"
        if not callback_url
        else None
    )

    agent_id, secret = get_agent_credentials()
    cid = output.correlation_id or get_correlation_id() or ""
    payload = _build_notification_payload(output, cid)
    body_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    target_path = urlparse(target_url).path
    headers = _build_notification_headers(
        agent_id=agent_id,
        secret=secret,
        cid=cid,
        method="POST",
        path=target_path,
        body_bytes=body_bytes,
    )

    timeout = getattr(settings, "EXECUTION_CALLBACK_TIMEOUT_SECONDS", 5.0)
    max_retries = getattr(settings, "EXECUTION_CALLBACK_MAX_RETRIES", 3)

    for attempt in range(max_retries):
        try:
            success, terminal, status_code, text = await _dispatch_webhook_http(
                target_url=target_url,
                fallback_url=fallback_url,
                payload=payload,
                headers=headers,
                timeout=timeout,
                agent_id=agent_id,
                secret=secret,
                cid=cid,
                body_bytes=body_bytes,
            )
            if success:
                logger.info(
                    "Notificación webhook entregada con éxito a '%s' (Status: %d, execution_id: %s).",
                    target_url,
                    status_code,
                    output.execution_id,
                )
                return True
            if terminal:
                logger.warning(
                    "Notificación webhook rechazada con código %d en '%s': %s",
                    status_code,
                    target_url,
                    text,
                )
                return False
            logger.warning(
                "Intento %d/%d de webhook a '%s' devolvió código %d: %s",
                attempt + 1,
                max_retries,
                target_url,
                status_code,
                text,
            )
        except httpx.RequestError as req_err:
            logger.warning(
                "Error de red en intento %d/%d al notificar webhook en '%s': %s",
                attempt + 1,
                max_retries,
                target_url,
                req_err,
            )
        except Exception as err:
            logger.warning(
                "Error inesperado al emitir notificación webhook a '%s': %s",
                target_url,
                err,
            )
            return False

        if attempt < max_retries - 1:
            await asyncio.sleep(0.5 * (2**attempt))

    logger.error(
        "Se agotaron los %d reintentos para entregar webhook de '%s' a '%s'.",
        max_retries,
        output.execution_id,
        target_url,
    )
    return False
