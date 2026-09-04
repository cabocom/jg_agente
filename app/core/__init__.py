"""Módulo Core de jg_agente: contratos, orquestación y runtime agnóstico."""

from app.core.boot import (
    BootIntegrityError,
    init_agent_capabilities,
    validate_boot_capabilities,
)
from app.core.checkpointer import (
    get_checkpointer,
    get_memory_checkpointer,
    get_postgres_checkpointer,
)
from app.core.config import Settings, settings
from app.core.plugin_manager import (
    PluginDependencyError,
    PluginLoadError,
    PluginManager,
)
from app.core.registry import BootConflictError, CapabilityRegistry

__all__ = [
    "BootConflictError",
    "BootIntegrityError",
    "CapabilityRegistry",
    "PluginDependencyError",
    "PluginLoadError",
    "PluginManager",
    "Settings",
    "get_checkpointer",
    "get_memory_checkpointer",
    "get_postgres_checkpointer",
    "init_agent_capabilities",
    "settings",
    "validate_boot_capabilities",
]
