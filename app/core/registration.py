"""Módulo de registro con jg_dashboard mediante bootstrap token y persistencia de credenciales."""

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import ValidationError

from app import __version__
from app.core.config import Settings
from app.core.registry import CapabilityRegistry
from app.models.registration import (
    AgentCredentials,
    AgentRegistrationPayload,
    AgentRegistrationResponse,
)
from app.security.auth import compute_canonical_string, compute_hmac_signature

logger = logging.getLogger("jg_agente.registration")


class RegistrationError(Exception):
    """Error base en el proceso de registro del agente con el Dashboard."""

    pass


class RegistrationAuthError(RegistrationError):
    """Error de autenticación: bootstrap token inválido, revocado o expirado (HTTP 401)."""

    pass


class RegistrationConflictError(RegistrationError):
    """Error de conflicto: bootstrap token ya consumido o agente ya registrado (HTTP 409)."""

    pass


class DashboardConnectionError(RegistrationError):
    """Fallo de conectividad o indisponibilidad temporal del Dashboard."""

    pass


class CredentialStore:
    """Gestiona el almacenamiento y carga persistente y segura de credenciales locales."""

    @staticmethod
    def resolve_path(
        path: Path | str | None, default_path: str = ".agent_credentials.json"
    ) -> Path:
        """Resuelve la ruta al archivo de credenciales."""
        return Path(path) if path is not None else Path(default_path)

    @classmethod
    def save(cls, credentials: AgentCredentials, path: Path | str | None = None) -> None:
        """Guarda las credenciales de forma atómica en formato JSON aplicando permisos 0600 en POSIX."""
        target = cls.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        data = credentials.model_dump(mode="json")
        json_content = json.dumps(data, indent=2, ensure_ascii=False)

        # Archivo temporal en el mismo directorio para garantizar atomicidad de os.replace en el mismo filesystem
        tmp_target = target.with_name(f"{target.name}.tmp")

        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(tmp_target, flags, 0o600)
        try:
            if os.name == "posix":
                try:
                    os.fchmod(fd, 0o600)
                except OSError as e:
                    logger.warning(
                        "No se pudieron restringir los permisos a 0600 en descriptor de %s: %s",
                        tmp_target,
                        e,
                    )
            with open(fd, "w", encoding="utf-8", closefd=True) as f:
                f.write(json_content)
                f.flush()
                os.fsync(f.fileno())

            # Reemplazo atómico
            os.replace(tmp_target, target)
        except Exception:
            if tmp_target.exists():
                with contextlib.suppress(OSError):
                    tmp_target.unlink(missing_ok=True)
            raise

        logger.info("Credenciales del agente guardadas atómicamente en: %s", target)

    @classmethod
    def load(cls, path: Path | str | None = None) -> AgentCredentials | None:
        """Carga las credenciales desde el archivo. Devuelve None si no existe o es corrupto."""
        target = cls.resolve_path(path)
        if not target.is_file():
            return None

        try:
            content = target.read_text(encoding="utf-8").strip()
            if not content:
                return None
            data = json.loads(content)
            return AgentCredentials.model_validate(data)
        except (json.JSONDecodeError, ValidationError, OSError) as e:
            logger.warning(
                "Archivo de credenciales en %s corrupto o inválido: %s",
                target,
                e,
            )
            return None

    @classmethod
    def exists(cls, path: Path | str | None = None) -> bool:
        """Comprueba si el archivo de credenciales existe."""
        return cls.resolve_path(path).is_file()

    @classmethod
    def clear(cls, path: Path | str | None = None) -> None:
        """Elimina el archivo de credenciales si existe."""
        target = cls.resolve_path(path)
        if target.is_file():
            try:
                target.unlink()
                logger.info("Archivo de credenciales eliminado: %s", target)
            except OSError as e:
                logger.error("Error al eliminar credenciales en %s: %s", target, e)


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

        endpoint_v1 = f"{self.dashboard_url}/api/v1/agents/register"
        endpoint_fallback = f"{self.dashboard_url}/api/agents/register"

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            last_exception: Exception | None = None

            for attempt in range(1, self.retries + 1):
                try:
                    logger.info(
                        "Intentando registrar agente con Dashboard en %s (intento %d/%d)...",
                        endpoint_v1,
                        attempt,
                        self.retries,
                    )

                    response = await client.post(
                        endpoint_v1,
                        json=payload.model_dump(exclude_none=True),
                        headers=headers,
                    )

                    # Si responde 404 en /api/v1, probar endpoint alternativo sin /v1
                    if response.status_code == 404:
                        logger.warning(
                            "Endpoint %s devolvió 404; reintentando con endpoint alternativo %s",
                            endpoint_v1,
                            endpoint_fallback,
                        )
                        response = await client.post(
                            endpoint_fallback,
                            json=payload.model_dump(exclude_none=True),
                            headers=headers,
                        )

                    # Evaluación de respuesta
                    if response.status_code == 200:
                        data = response.json()
                        reg_response = AgentRegistrationResponse.model_validate(data)
                        logger.info(
                            "¡Registro exitoso con Dashboard! Agent ID: %s, Nombre: %s",
                            reg_response.agent_id,
                            reg_response.name,
                        )
                        return reg_response

                    if response.status_code == 401:
                        err_msg = (
                            response.json().get("message")
                            if response.headers.get("content-type", "").startswith(
                                "application/json"
                            )
                            else response.text
                        )
                        msg = f"Bootstrap token rechazado o expirado (HTTP 401): {err_msg}"
                        logger.error(msg)
                        raise RegistrationAuthError(msg)

                    if response.status_code == 409:
                        err_msg = (
                            response.json().get("message")
                            if response.headers.get("content-type", "").startswith(
                                "application/json"
                            )
                            else response.text
                        )
                        msg = f"Bootstrap token en conflicto o ya consumido (HTTP 409): {err_msg}"
                        logger.error(msg)
                        raise RegistrationConflictError(msg)

                    # Para errores 5xx del servidor, intentar reintento
                    if response.status_code >= 500:
                        msg = (
                            f"Dashboard devolvió error HTTP {response.status_code}: {response.text}"
                        )
                        logger.warning(msg)
                        last_exception = DashboardConnectionError(msg)
                    else:
                        msg = f"Fallo no recuperable de registro (HTTP {response.status_code}): {response.text}"
                        logger.error(msg)
                        raise RegistrationError(msg)

                except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                    msg = f"Error de conectividad al contactar con el Dashboard ({self.dashboard_url}): {e}"
                    logger.warning(msg)
                    last_exception = DashboardConnectionError(msg)

                # Backoff exponencial antes de reintentar
                if attempt < self.retries:
                    sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                    logger.info(
                        "Esperando %.2f segundos antes del siguiente intento...", sleep_time
                    )
                    await asyncio.sleep(sleep_time)

            # Si se agotaron los reintentos
            final_msg = f"No se pudo completar el registro tras {self.retries} intentos. Último error: {last_exception}"
            logger.error(final_msg)
            if isinstance(last_exception, RegistrationError):
                raise last_exception
            raise DashboardConnectionError(final_msg) from last_exception

    async def verify_credentials(
        self,
        agent_id: str,
        permanent_secret: str,
    ) -> dict[str, Any]:
        """Verifica activamente la credencial permanente contra el endpoint de heartbeat del Dashboard."""
        token = permanent_secret.strip()
        aid = agent_id.strip()
        if not token or not aid:
            raise RegistrationAuthError("Identificador de agente o credencial permanente vacíos.")

        payload = {
            "agent_id": aid,
            "status": "ACTIVE",
            "metrics": {
                "source": "boot_verification",
            },
        }

        timestamp = int(time.time())
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        canonical_v1 = compute_canonical_string(
            "POST", "/api/v1/agents/heartbeat", timestamp, raw_body
        )
        sig_v1 = compute_hmac_signature(token, canonical_v1)

        headers = {
            "Authorization": f"Bearer {token}",
            "X-Agent-ID": aid,
            "X-Agent-Secret": token,
            "X-Timestamp": str(timestamp),
            "X-Signature": sig_v1,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"jg_agente/{__version__}",
        }

        endpoint_v1 = f"{self.dashboard_url}/api/v1/agents/heartbeat"
        endpoint_fallback = f"{self.dashboard_url}/api/agents/heartbeat"

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            try:
                response = await client.post(endpoint_v1, content=raw_body, headers=headers)
                if response.status_code == 404:
                    canonical_fallback = compute_canonical_string(
                        "POST", "/api/agents/heartbeat", timestamp, raw_body
                    )
                    headers_fallback = dict(headers)
                    headers_fallback["X-Signature"] = compute_hmac_signature(
                        token, canonical_fallback
                    )
                    response = await client.post(
                        endpoint_fallback, content=raw_body, headers=headers_fallback
                    )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(
                        "Credenciales permanentes verificadas exitosamente con Dashboard (Agent ID: %s).",
                        aid,
                    )
                    return cast(dict[str, Any], data)

                if response.status_code in (401, 403):
                    msg = (
                        f"Credencial permanente rechazada o revocada por el Dashboard "
                        f"(HTTP {response.status_code}): {response.text}"
                    )
                    logger.critical(msg)
                    raise RegistrationAuthError(msg)

                msg = f"Fallo al verificar credencial permanente (HTTP {response.status_code}): {response.text}"
                logger.warning(msg)
                raise RegistrationError(msg)

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                msg = f"No fue posible contactar con el Dashboard ({self.dashboard_url}) para verificar credenciales: {e}"
                logger.warning(msg)
                raise DashboardConnectionError(msg) from e


def reload_credentials(
    settings: Settings,
    store: type[CredentialStore] = CredentialStore,
) -> AgentCredentials | None:
    """Recarga las credenciales desde el almacenamiento local y sincroniza los settings en memoria."""
    persisted = store.load(settings.CREDENTIALS_FILE)
    if persisted is not None:
        settings.AGENT_ID = persisted.agent_id
        settings.PERMANENT_AGENT_SECRET = persisted.permanent_secret
        logger.info(
            "Credenciales recargadas exitosamente desde %s (Agent ID: %s).",
            settings.CREDENTIALS_FILE,
            persisted.agent_id,
        )
        return persisted
    return None


async def auto_register_agent(
    settings: Settings,
    registry: CapabilityRegistry | None = None,
    client: DashboardRegistrationClient | None = None,
    store: type[CredentialStore] = CredentialStore,
) -> AgentCredentials | None:
    """Comprueba credenciales existentes o ejecuta el registro mediante bootstrap token durante el boot."""
    reg_client = client or DashboardRegistrationClient(
        dashboard_url=settings.DASHBOARD_URL,
        timeout=settings.DASHBOARD_REGISTRATION_TIMEOUT,
        retries=settings.DASHBOARD_REGISTRATION_RETRIES,
    )

    # 1. Comprobar si ya existe credencial permanente en variables de entorno / settings
    if (
        settings.PERMANENT_AGENT_SECRET
        and settings.AGENT_ID
        and settings.AGENT_ID != "jg_agente_local"
    ):
        logger.info(
            "Agente preautenticado mediante PERMANENT_AGENT_SECRET en configuración (Agent ID: %s).",
            settings.AGENT_ID,
        )
        creds = AgentCredentials(
            agent_id=settings.AGENT_ID,
            permanent_secret=settings.PERMANENT_AGENT_SECRET,
            agent_name=settings.AGENT_NAME,
            dashboard_url=settings.DASHBOARD_URL,
        )

        if settings.VERIFY_CREDENTIALS_ON_BOOT:
            try:
                await reg_client.verify_credentials(creds.agent_id, creds.permanent_secret)
                creds.verified = True
            except RegistrationAuthError:
                logger.critical("Credenciales de entorno rechazadas por el Dashboard (HTTP 401).")
                raise
            except DashboardConnectionError as e:
                logger.warning(
                    "Dashboard no disponible temporalmente (%s). Continuando con credenciales de entorno.",
                    e,
                )

        return creds

    # 2. Comprobar si existen credenciales persistidas en disco
    persisted = store.load(settings.CREDENTIALS_FILE)
    if persisted is not None:
        logger.info(
            "Credenciales recuperadas del almacenamiento local '%s' (Agent ID: %s, Nombre: %s).",
            settings.CREDENTIALS_FILE,
            persisted.agent_id,
            persisted.agent_name,
        )
        settings.AGENT_ID = persisted.agent_id
        settings.PERMANENT_AGENT_SECRET = persisted.permanent_secret

        if settings.VERIFY_CREDENTIALS_ON_BOOT:
            try:
                await reg_client.verify_credentials(persisted.agent_id, persisted.permanent_secret)
                persisted.verified = True
            except RegistrationAuthError:
                logger.critical(
                    "Credenciales locales rechazadas o revocadas por el Dashboard (HTTP 401). Limpiando archivo local."
                )
                store.clear(settings.CREDENTIALS_FILE)
                raise
            except DashboardConnectionError as e:
                logger.warning(
                    "Dashboard no disponible temporalmente (%s). Continuando con credenciales locales.",
                    e,
                )

        return persisted

    # 3. Si no hay credenciales persistidas, verificar si se suministró AGENT_BOOTSTRAP_TOKEN
    bootstrap_token = settings.AGENT_BOOTSTRAP_TOKEN
    if bootstrap_token and bootstrap_token.strip():
        logger.info(
            "Detectado AGENT_BOOTSTRAP_TOKEN. Iniciando proceso de aprovisionamiento Zero-Trust con Dashboard..."
        )

        capabilities_summary = registry.get_capabilities_summary() if registry is not None else None
        agent_name = settings.AGENT_NAME or settings.AGENT_ID

        metadata = {
            "environment": settings.ENV,
            "port": settings.AGENT_PORT,
            "registered_from": "auto_bootstrap",
        }

        try:
            response = await reg_client.register(
                bootstrap_token=bootstrap_token,
                agent_name=agent_name,
                version=__version__,
                capabilities=capabilities_summary,
                metadata=metadata,
            )

            credentials = AgentCredentials(
                agent_id=response.agent_id,
                permanent_secret=response.permanent_secret,
                agent_name=response.name,
                dashboard_url=settings.DASHBOARD_URL,
                registered_at=response.registered_at,
                verified=True,
            )

            # Persistir credenciales en disco de forma segura
            store.save(credentials, settings.CREDENTIALS_FILE)

            # Actualizar settings en memoria
            settings.AGENT_ID = credentials.agent_id
            settings.PERMANENT_AGENT_SECRET = credentials.permanent_secret

            logger.info(
                "Aprovisionamiento completado con éxito. El agente queda registrado como '%s' (%s).",
                credentials.agent_name,
                credentials.agent_id,
            )
            return credentials

        except Exception as e:
            logger.error("Error durante el aprovisionamiento con bootstrap token: %s", e)
            if settings.REQUIRE_DASHBOARD_REGISTRATION:
                raise
            return None

    # 4. Sin bootstrap token ni credenciales locales
    if settings.REQUIRE_DASHBOARD_REGISTRATION:
        msg = (
            "El agente está configurado con REQUIRE_DASHBOARD_REGISTRATION=True pero no se encontró "
            "ningún AGENT_BOOTSTRAP_TOKEN ni archivo de credenciales válido."
        )
        logger.critical(msg)
        raise RegistrationError(msg)

    logger.warning(
        "No se encontró AGENT_BOOTSTRAP_TOKEN ni credenciales persistidas. "
        "El agente arrancará en modo local/desconectado (Agent ID: %s).",
        settings.AGENT_ID,
    )
    return None
