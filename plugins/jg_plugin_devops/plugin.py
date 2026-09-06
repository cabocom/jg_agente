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
        self._discovery_engine: BaseEngine | None = None
        self._planner_engine: BaseEngine | None = None
        self._verifier_engine: BaseEngine | None = None

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

        Registra DockerRestartTool (docker_restart) para reinicio seguro con compensación (rollback).
        """
        from jg_plugin_devops.docker_tools import create_docker_restart_tool

        return [create_docker_restart_tool()]

    def register_engines(self) -> dict[str, BaseEngine]:
        """Declara los motores de dominio provistos por el plugin.

        Registra:
        - InfraDiscoveryEngine como ObserverEngine (observabilidad y telemetría)
        - DAGPlannerEngine como PlannerEngine (planificación de pasos y riesgos)
        - DevopsVerifierEngine como VerifierEngine (verificación post-acción)
        """
        from jg_plugin_devops.discovery import InfraDiscoveryEngine
        from jg_plugin_devops.planner import DAGPlannerEngine
        from jg_plugin_devops.verifier import DevopsVerifierEngine

        if self._discovery_engine is None:
            self._discovery_engine = InfraDiscoveryEngine()
        if self._planner_engine is None:
            self._planner_engine = DAGPlannerEngine()
        if self._verifier_engine is None:
            self._verifier_engine = DevopsVerifierEngine()

        return {
            "infra_discovery": self._discovery_engine,
            "dag_planner": self._planner_engine,
            "devops_verifier": self._verifier_engine,
        }

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
        for eng in (self._discovery_engine, self._planner_engine, self._verifier_engine):
            if eng is not None:
                await eng.startup()
        self._is_started = True

    async def shutdown(self) -> None:
        """Liberación asíncrona de recursos al detener el agente."""
        logger.info("Deteniendo DevOpsPlugin...")
        for eng in (self._discovery_engine, self._planner_engine, self._verifier_engine):
            if eng is not None:
                await eng.shutdown()
        self._is_started = False

    async def health_check(self) -> dict[str, Any]:
        """Comprueba y reporta el estado de salud del plugin DevOps y sus motores."""
        engines_status: dict[str, str] = {}
        for name, eng in (
            ("infra_discovery", self._discovery_engine),
            ("dag_planner", self._planner_engine),
            ("devops_verifier", self._verifier_engine),
        ):
            engines_status[name] = (
                "started" if (eng is not None and getattr(eng, "_is_started", False)) else "idle"
            )

        return {
            "status": "ok",
            "plugin": self.name,
            "version": "0.1.0",
            "started": self._is_started,
            "engines": engines_status,
        }


PLUGIN_CLASS = DevOpsPlugin
