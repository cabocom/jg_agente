# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo Core de jg_agente: contratos, orquestación y runtime agnóstico."""

from app.core.boot import (
    BootIntegrityError,
    init_agent_capabilities,
    validate_boot_capabilities,
)
from app.core.checkpointer import (
    DualPostgresSaver,
    close_checkpointer,
    get_checkpointer,
    get_memory_checkpointer,
    get_postgres_checkpointer,
)
from app.core.config import Settings, settings
from app.core.graph import GraphBuilder, GraphTopologyInfo, build_agent_graph
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
    "DualPostgresSaver",
    "GraphBuilder",
    "GraphTopologyInfo",
    "PluginDependencyError",
    "PluginLoadError",
    "PluginManager",
    "Settings",
    "build_agent_graph",
    "close_checkpointer",
    "get_checkpointer",
    "get_memory_checkpointer",
    "get_postgres_checkpointer",
    "init_agent_capabilities",
    "settings",
    "validate_boot_capabilities",
]
