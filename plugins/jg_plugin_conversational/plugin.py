"""Implementación de la clase principal del plugin conversacional para jg_agente.

Cumple estrictamente con la interfaz canónica BasePlugin y el ciclo de vida
del agente cognitivo sin introducir dependencias hacia DevOps ni Asterisk directo.
"""

import logging
from typing import Any

from app.models.tools import AgentTool
from app.plugins.base import BaseEngine, BasePlugin, PluginMetadata

logger = logging.getLogger("jg_plugin_conversational")


class ConversationalPlugin(BasePlugin):
    """Plugin de capacidades conversacionales para jg_agente."""

    def __init__(self) -> None:
        self._is_started: bool = False

    def get_plugin_metadata(self) -> PluginMetadata:
        """Retorna los metadatos canónicos del plugin conversacional."""
        return PluginMetadata(
            name="conversational",
            version="0.1.0",
            description="Plugin de diálogo e interacción en lenguaje natural para jg_agente",
            author="Javier Gálvez",
            dependencies=[],
            jg_agente_version_min="0.1.0",
            tags=["conversational", "nlp", "interaction"],
        )

    def register_tools(self) -> list[AgentTool]:
        """Declara la lista de AgentTool provistas por el plugin conversacional.

        En esta fase estructural inicial retorna lista vacía. Las herramientas
        específicas se incorporan en tareas sucesivas.
        """
        return []

    def register_engines(self) -> dict[str, BaseEngine]:
        """Declara los motores cognitivos provistos por el plugin.

        El agente conversacional puro no requiere motores de planificación complejos
        ni observadores de infraestructura pesada.
        """
        return {}

    async def startup(self) -> None:
        """Inicialización asíncrona durante el boot del agente."""
        logger.info("Inicializando ConversationalPlugin v0.1.0...")
        self._is_started = True

    async def shutdown(self) -> None:
        """Liberación asíncrona de recursos al detener el agente."""
        logger.info("Deteniendo ConversationalPlugin...")
        self._is_started = False

    async def health_check(self) -> dict[str, Any]:
        """Comprueba y reporta el estado de salud del plugin conversacional."""
        return {
            "status": "ok",
            "plugin": self.name,
            "version": "0.1.0",
            "started": self._is_started,
        }


PLUGIN_CLASS = ConversationalPlugin
