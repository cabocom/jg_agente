# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Cliente HTTP asíncrono para registro y verificación de credenciales con el Dashboard."""

import asyncio
import json
import logging
import secrets
import time
from typing import Any, cast

import httpx

from app import __version__
from app.core.registration_store import (
    DashboardConnectionError,
    RegistrationAuthError,
    RegistrationConflictError,
    RegistrationError,
)
from app.models.registration import (
    AgentRegistrationPayload,
    AgentRegistrationResponse,
)
from app.security.auth import compute_canonical_string, compute_hmac_signature

logger = logging.getLogger("jg_agente.registration.client")


def _handle_registration_http_error(response: httpx.Response) -> None:
    """Evalúa errores HTTP específicos devueltos por el Dashboard durante el registro."""
    is_json = response.headers.get("content-type", "").startswith("application/json")
    err_msg = response.json().get("message") if is_json else response.text
    if response.status_code == 401:
        msg = f"Bootstrap token rechazado o expirado (HTTP 401): {err_msg}"
        logger.error(msg)
        raise RegistrationAuthError(msg)
    if response.status_code == 409:
        msg = f"Bootstrap token en conflicto o ya consumido (HTTP 409): {err_msg}"
        logger.error(msg)
        raise RegistrationConflictError(msg)


async def _execute_registration_attempt(
    client: httpx.AsyncClient,
    endpoint_v1: str,
    endpoint_fallback: str,
    payload: AgentRegistrationPayload,
    headers: dict[str, str],
) -> AgentRegistrationResponse:
    """Ejecuta una petición de registro contra endpoint principal o fallback."""
    data = payload.model_dump(exclude_none=True)
    response = await client.post(endpoint_v1, json=data, headers=headers)
    if response.status_code == 404:
        logger.warning(
            "Endpoint %s devolvió 404; reintentando con fallback %s",
            endpoint_v1,
            endpoint_fallback,
        )
        response = await client.post(endpoint_fallback, json=data, headers=headers)

    if response.status_code == 200:
        reg_response = AgentRegistrationResponse.model_validate(response.json())
        logger.info(
            "¡Registro exitoso con Dashboard! Agent ID: %s, Nombre: %s",
            reg_response.agent_id,
            reg_response.name,
        )
        return reg_response

    _handle_registration_http_error(response)
    if response.status_code >= 500:
        msg = f"Dashboard devolvió error HTTP {response.status_code}: {response.text}"
        logger.warning(msg)
        raise DashboardConnectionError(msg)

    msg = f"Fallo no recuperable de registro (HTTP {response.status_code}): {response.text}"
    logger.error(msg)
    raise RegistrationError(msg)


def _build_signed_heartbeat(aid: str, token: str) -> tuple[bytes, dict[str, str], int]:
    """Genera el payload y cabeceras HMAC firmadas para verificación de credenciales."""
    payload = {"agent_id": aid, "status": "ACTIVE", "metrics": {"source": "boot_verification"}}
    timestamp = int(time.time())
    nonce = secrets.token_hex(16)
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    canonical_v1 = compute_canonical_string(
        "POST", "/api/v1/agents/heartbeat", timestamp, raw_body, nonce=nonce
    )
    sig_v1 = compute_hmac_signature(token, canonical_v1)
    headers = {
        "X-Agent-ID": aid,
        "X-Timestamp": str(timestamp),
        "X-Nonce": nonce,
        "X-Signature": sig_v1,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"jg_agente/{__version__}",
    }
    return raw_body, headers, timestamp


async def _send_heartbeat_request(
    client: httpx.AsyncClient,
    dashboard_url: str,
    raw_body: bytes,
    headers: dict[str, str],
    timestamp: int,
    token: str,
) -> httpx.Response:
    """Envía la solicitud de heartbeat intentando /v1 y fallback."""
    v1_url = f"{dashboard_url}/api/v1/agents/heartbeat"
    fallback_url = f"{dashboard_url}/api/agents/heartbeat"
    response = await client.post(v1_url, content=raw_body, headers=headers)
    if response.status_code == 404:
        nonce = headers.get("X-Nonce")
        can_fb = compute_canonical_string(
            "POST", "/api/agents/heartbeat", timestamp, raw_body, nonce=nonce
        )
        headers_fb = dict(headers)
        headers_fb["X-Signature"] = compute_hmac_signature(token, can_fb)
        response = await client.post(fallback_url, content=raw_body, headers=headers_fb)
    return response


async def _retry_registration(
    client: httpx.AsyncClient,
    v1_url: str,
    fallback_url: str,
    payload: AgentRegistrationPayload,
    headers: dict[str, str],
    retries: int,
    backoff_factor: float,
    dashboard_url: str,
) -> AgentRegistrationResponse:
    """Ejecuta los reintentos con backoff exponencial para el registro."""
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await _execute_registration_attempt(
                client, v1_url, fallback_url, payload, headers
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = DashboardConnectionError(f"Error conectando con {dashboard_url}: {e}")
        except DashboardConnectionError as e:
            last_exc = e

        if attempt < retries:
            await asyncio.sleep(backoff_factor * (2 ** (attempt - 1)))

    final_msg = f"No se pudo completar el registro tras {retries} intentos: {last_exc}"
    logger.error(final_msg)
    if isinstance(last_exc, RegistrationError):
        raise last_exc
    raise DashboardConnectionError(final_msg) from last_exc


class DashboardRegistrationClient:
    """Cliente HTTP asíncrono para consumir bootstrap tokens y registrar el agente en el Dashboard."""

    def __init__(
        self,
        dashboard_url: str = "http://jg_dashboard:8080",
        timeout: float = 10.0,
        retries: int = 3,
        backoff_factor: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.dashboard_url = dashboard_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.transport = transport

    async def register(
        self,
        bootstrap_token: str,
        agent_name: str | None = None,
        version: str | None = None,
        capabilities: dict[str, Any] | list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRegistrationResponse:
        """Envía solicitud de registro al Dashboard con reintentos exponenciales ante fallos transitorios."""
        token = bootstrap_token.strip()
        if not token:
            raise RegistrationAuthError("El bootstrap token no puede estar vacío.")

        payload = AgentRegistrationPayload(
            bootstrap_token=token,
            agent_name=agent_name,
            version=version or __version__,
            capabilities=capabilities,
            metadata=metadata or {},
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"jg_agente/{__version__}",
        }
        v1_url = f"{self.dashboard_url}/api/v1/agents/register"
        fallback_url = f"{self.dashboard_url}/api/agents/register"

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            return await _retry_registration(
                client,
                v1_url,
                fallback_url,
                payload,
                headers,
                self.retries,
                self.backoff_factor,
                self.dashboard_url,
            )

    async def verify_credentials(
        self,
        agent_id: str,
        permanent_secret: str,
    ) -> dict[str, Any]:
        """Verifica activamente la credencial permanente contra el endpoint de heartbeat del Dashboard."""
        token, aid = permanent_secret.strip(), agent_id.strip()
        if not token or not aid:
            raise RegistrationAuthError("Identificador de agente o credencial permanente vacíos.")

        raw_body, headers, timestamp = _build_signed_heartbeat(aid, token)

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            try:
                resp = await _send_heartbeat_request(
                    client, self.dashboard_url, raw_body, headers, timestamp, token
                )
                if resp.status_code == 200:
                    logger.info("Credenciales permanentes verificadas (Agent ID: %s).", aid)
                    return cast(dict[str, Any], resp.json())
                if resp.status_code in (401, 403):
                    msg = f"Credencial permanente rechazada por Dashboard (HTTP {resp.status_code}): {resp.text}"
                    logger.critical(msg)
                    raise RegistrationAuthError(msg)
                msg = f"Fallo al verificar credencial permanente (HTTP {resp.status_code}): {resp.text}"
                logger.warning(msg)
                raise RegistrationError(msg)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                msg = f"No fue posible contactar con Dashboard ({self.dashboard_url}): {e}"
                logger.warning(msg)
                raise DashboardConnectionError(msg) from e
