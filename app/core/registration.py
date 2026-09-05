"""Módulo de registro con jg_dashboard mediante bootstrap token y persistencia de credenciales."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

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
        """Guarda las credenciales en formato JSON aplicando permisos restrictivos 0600 en POSIX."""
        target = cls.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        data = credentials.model_dump(mode="json")
        json_content = json.dumps(data, indent=2, ensure_ascii=False)

        # Escribir archivo
        target.write_text(json_content, encoding="utf-8")

        # Aplicar permisos 0600 (lectura/escritura sólo para el propietario) en POSIX
        if os.name == "posix":
            try:
                os.chmod(target, 0o600)
            except OSError as e:
                logger.warning(
                    "No se pudieron restringir los permisos a 0600 en %s: %s",
                    target,
                    e,
                )

        logger.info("Credenciales del agente guardadas de forma segura en: %s", target)

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


async def auto_register_agent(
    settings: Settings,
    registry: CapabilityRegistry | None = None,
    client: DashboardRegistrationClient | None = None,
    store: type[CredentialStore] = CredentialStore,
) -> AgentCredentials | None:
    """Comprueba credenciales existentes o ejecuta el registro mediante bootstrap token durante el boot."""
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
        return AgentCredentials(
            agent_id=settings.AGENT_ID,
            permanent_secret=settings.PERMANENT_AGENT_SECRET,
            agent_name=settings.AGENT_NAME,
            dashboard_url=settings.DASHBOARD_URL,
        )

    # 2. Comprobar si existen credenciales persistidas en disco
    persisted = store.load(settings.CREDENTIALS_FILE)
    if persisted is not None:
        logger.info(
            "Credenciales recuperadas del almacenamiento local '%s' (Agent ID: %s, Nombre: %s).",
            settings.CREDENTIALS_FILE,
            persisted.agent_id,
            persisted.agent_name,
        )
        # Sincronizar settings en memoria
        settings.AGENT_ID = persisted.agent_id
        settings.PERMANENT_AGENT_SECRET = persisted.permanent_secret
        return persisted

    # 3. Si no hay credenciales persistidas, verificar si se suministró AGENT_BOOTSTRAP_TOKEN
    bootstrap_token = settings.AGENT_BOOTSTRAP_TOKEN
    if bootstrap_token and bootstrap_token.strip():
        logger.info(
            "Detectado AGENT_BOOTSTRAP_TOKEN. Iniciando proceso de aprovisionamiento Zero-Trust con Dashboard..."
        )

        reg_client = client or DashboardRegistrationClient(
            dashboard_url=settings.DASHBOARD_URL,
            timeout=settings.DASHBOARD_REGISTRATION_TIMEOUT,
            retries=settings.DASHBOARD_REGISTRATION_RETRIES,
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
