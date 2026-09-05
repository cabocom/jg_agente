"""Implementación de la clase principal del plugin DevOps para jg_agente.

Cumple estrictamente con la interfaz canónica BasePlugin y el ciclo de vida
del agente cognitivo sin alterar el Core ni romper el agnosticismo de dominio.
"""

import logging
from typing import Any

from pydantic import BaseModel

from app.models.tools import AgentTool
from app.plugins.base import BaseEngine, BasePlugin, PluginMetadata
from jg_plugin_devops.models.snapshot import (
    DockerSnapshot,
    HostSnapshot,
    InfraIncident,
    InfraSnapshot,
    KubernetesSnapshot,
)

logger = logging.getLogger("jg_plugin_devops")


class DevOpsPlugin(BasePlugin):
    """Plugin de operaciones de infraestructura, observabilidad y SRE para jg_agente."""

    def __init__(self) -> None:
        self._is_started: bool = False

    def get_plugin_metadata(self) -> PluginMetadata:
        """Retorna los metadatos canónicos del plugin DevOps."""
        return PluginMetadata(
            name="devops",
            version="0.1.0",
            description="Plugin de operaciones de infraestructura, observabilidad y SRE para jg_agente",
            author="Javier Gálvez",
            dependencies=[],
            jg_agente_version_min="0.1.0",
            tags=["devops", "infrastructure", "docker", "kubernetes", "observability", "sre"],
        )

    def register_tools(self) -> list[AgentTool]:
        """Declara la lista de AgentTool provistas por el plugin DevOps.

        En esta fase de estructura y modelos, la lista inicial es vacía.
        Las herramientas operativas se incorporarán en las siguientes tareas de la fase.
        """
        return []

    def register_engines(self) -> dict[str, BaseEngine]:
        """Declara los motores de dominio provistos por el plugin.

        Motores como InfraDiscoveryEngine se integrarán en tareas subsiguientes.
        """
        return {}

    def register_models(self) -> dict[str, type[BaseModel]]:
        """Registra los modelos Pydantic de infraestructura expuestos por el plugin."""
        return {
            "InfraSnapshot": InfraSnapshot,
            "HostSnapshot": HostSnapshot,
            "DockerSnapshot": DockerSnapshot,
            "KubernetesSnapshot": KubernetesSnapshot,
            "InfraIncident": InfraIncident,
        }

    async def startup(self) -> None:
        """Inicialización asíncrona durante el arranque del agente."""
        logger.info("Inicializando DevOpsPlugin v0.1.0...")
        self._is_started = True

    async def shutdown(self) -> None:
        """Liberación asíncrona de recursos al detener el agente."""
        logger.info("Deteniendo DevOpsPlugin...")
        self._is_started = False

    async def health_check(self) -> dict[str, Any]:
        """Comprueba y reporta el estado de salud del plugin DevOps."""
        return {
            "status": "ok",
            "plugin": self.name,
            "version": "0.1.0",
            "started": self._is_started,
        }


PLUGIN_CLASS = DevOpsPlugin
