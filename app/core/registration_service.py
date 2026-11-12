# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicios de aprovisionamiento de credenciales y registro automático para jg_agente."""

import logging
from typing import Any

from app import __version__
from app.core.config import Settings
from app.core.registration_client import DashboardRegistrationClient
from app.core.registration_store import (
    CredentialStore,
    DashboardConnectionError,
    RegistrationAuthError,
    RegistrationError,
)
from app.core.registry import CapabilityRegistry
from app.models.registration import AgentCredentials

logger = logging.getLogger("jg_agente.registration.service")


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


async def _try_environment_credentials(
    settings: Settings,
    reg_client: DashboardRegistrationClient,
) -> AgentCredentials | None:
    """Comprueba si el agente está preautenticado en variables de entorno."""
    if not (
        settings.PERMANENT_AGENT_SECRET
        and settings.AGENT_ID
        and settings.AGENT_ID != "jg_agente_local"
    ):
        return None

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


async def _try_persisted_credentials(
    settings: Settings,
    reg_client: DashboardRegistrationClient,
    store: type[CredentialStore],
) -> AgentCredentials | None:
    """Comprueba si existen credenciales válidas en almacenamiento local."""
    persisted = store.load(settings.CREDENTIALS_FILE)
    if persisted is None:
        return None

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


def _persist_provisioned_credentials(
    response: Any,
    settings: Settings,
    store: type[CredentialStore],
) -> AgentCredentials:
    """Persiste y sincroniza las credenciales recibidas tras un aprovisionamiento exitoso."""
    credentials = AgentCredentials(
        agent_id=response.agent_id,
        permanent_secret=response.permanent_secret,
        agent_name=response.name,
        dashboard_url=settings.DASHBOARD_URL,
        registered_at=response.registered_at,
        verified=True,
    )
    store.save(credentials, settings.CREDENTIALS_FILE)
    settings.AGENT_ID = credentials.agent_id
    settings.PERMANENT_AGENT_SECRET = credentials.permanent_secret
    logger.info(
        "Aprovisionamiento completado con éxito. El agente queda registrado como '%s' (%s).",
        credentials.agent_name,
        credentials.agent_id,
    )
    return credentials


async def _provision_from_bootstrap_token(
    settings: Settings,
    registry: CapabilityRegistry | None,
    reg_client: DashboardRegistrationClient,
    store: type[CredentialStore],
) -> AgentCredentials | None:
    """Ejecuta el aprovisionamiento Zero-Trust con el Dashboard si hay bootstrap token."""
    bootstrap_token = settings.AGENT_BOOTSTRAP_TOKEN
    if not (bootstrap_token and bootstrap_token.strip()):
        return None

    logger.info(
        "Detectado AGENT_BOOTSTRAP_TOKEN. Iniciando proceso de aprovisionamiento Zero-Trust..."
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
        return _persist_provisioned_credentials(response, settings, store)
    except Exception as e:
        logger.error("Error durante el aprovisionamiento con bootstrap token: %s", e)
        if settings.REQUIRE_DASHBOARD_REGISTRATION:
            raise
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

    creds = await _try_environment_credentials(
        settings, reg_client
    ) or await _try_persisted_credentials(settings, reg_client, store)
    if creds is not None:
        return creds

    boot_creds = await _provision_from_bootstrap_token(settings, registry, reg_client, store)
    if boot_creds is not None:
        return boot_creds

    if settings.REQUIRE_DASHBOARD_REGISTRATION:
        msg = (
            "El agente está configurado con REQUIRE_DASHBOARD_REGISTRATION=True pero no se encontró "
            "ningún AGENT_BOOTSTRAP_TOKEN ni archivo de credenciales válido."
        )
        logger.critical(msg)
        raise RegistrationError(msg)

    logger.warning(
        "No se encontró AGENT_BOOTSTRAP_TOKEN ni credenciales persistidas. Arranca en modo desconectado (ID: %s).",
        settings.AGENT_ID,
    )
    return None
