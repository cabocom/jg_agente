"""Módulo Core de jg_agente: contratos, orquestación y runtime agnóstico."""

from app.core.checkpointer import (
    get_checkpointer,
    get_memory_checkpointer,
    get_postgres_checkpointer,
)
from app.core.config import Settings, settings
from app.core.registry import BootConflictError, CapabilityRegistry

__all__ = [
    "BootConflictError",
    "CapabilityRegistry",
    "Settings",
    "get_checkpointer",
    "get_memory_checkpointer",
    "get_postgres_checkpointer",
    "settings",
]
