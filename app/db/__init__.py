# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo de persistencia y base de datos relacional de jg_agente."""

from app.db.base import Base, core_metadata
from app.db.exceptions import PersistenceError
from app.db.models import CoreAuditRecord, CoreExecution
from app.db.session import async_engine, async_session_factory, get_async_session

__all__ = [
    "Base",
    "CoreAuditRecord",
    "CoreExecution",
    "PersistenceError",
    "async_engine",
    "async_session_factory",
    "core_metadata",
    "get_async_session",
]
