# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo unificado de registro con jg_dashboard mediante bootstrap token y credenciales."""

from app.core.registration_client import DashboardRegistrationClient
from app.core.registration_service import (
    auto_register_agent,
    reload_credentials,
)
from app.core.registration_store import (
    CredentialStore,
    DashboardConnectionError,
    RegistrationAuthError,
    RegistrationConflictError,
    RegistrationError,
)

__all__ = [
    "CredentialStore",
    "DashboardConnectionError",
    "DashboardRegistrationClient",
    "RegistrationAuthError",
    "RegistrationConflictError",
    "RegistrationError",
    "auto_register_agent",
    "reload_credentials",
]
