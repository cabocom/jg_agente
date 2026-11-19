# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Registro central de capacidades (CapabilityRegistry) de jg_agente.

Gestiona la indexación de herramientas (AgentTool), motores de dominio (BaseEngine)
y plugins (BasePlugin) delegando en sub-registros especializados (SOLID/ISP).
"""

from typing import Any, cast

from pydantic import BaseModel

from app.core.registry_subregistries import (
    RISK_WEIGHTS,
    BootConflictError,
    EngineRegistry,
    PluginCatalog,
    ToolRegistry,
)
from app.models.tools import AgentTool
from app.plugins.base import BasePlugin


def _extract_input_schema(tool: AgentTool) -> dict[str, Any]:
    """Extrae el JSON Schema del modelo Pydantic de argumentos o un objeto abierto por defecto."""
    schema = getattr(tool, "args_schema", None)
    if schema is not None and hasattr(schema, "model_json_schema"):
        return cast(dict[str, Any], schema.model_json_schema())
    return {"type": "object", "properties": {}, "additionalProperties": True}


class CapabilityRegistry:
    """Catálogo centralizado de capacidades que delega en sub-registros especializados."""

    SINGLETON_ENGINE_TYPES: frozenset[str] = frozenset({"observer", "planner", "verifier"})

    def __init__(self) -> None:
        self.tools = ToolRegistry()
        self.engines = EngineRegistry()
        self.plugins = PluginCatalog()

    # --- Fachadas para Compatibilidad Hacia Atrás (Regla 8.3 AGENTS.md) ---
    @property
    def _tools(self) -> dict[str, AgentTool]:
        return self.tools._tools

    @property
    def _engines(self) -> dict[str, Any]:
        return self.engines._engines

    @property
    def _singleton_engines(self) -> dict[str, Any]:
        return self.engines._singleton_engines

    @property
    def _plugins(self) -> dict[str, BasePlugin]:
        return self.plugins._plugins

    @property
    def _models(self) -> dict[str, type[BaseModel]]:
        return self.plugins._models

    def __getattr__(self, name: str) -> Any:
        """Delegación transparente a sub-registros para compatibilidad total con métodos existentes."""
        delegates = {
            "register_tool": self.tools.register,
            "get_tool": self.tools.get,
            "has_tool": self.tools.has,
            "list_tools": self.tools.list,
            "get_langchain_tools": self.tools.get_langchain_tools,
            "tool_names": self.tools.names,
            "register_engine": self.engines.register,
            "get_engine": self.engines.get,
            "get_engine_by_type": self.engines.get_by_type,
            "get_observer": self.engines.get_observer,
            "get_planner": self.engines.get_planner,
            "get_verifier": self.engines.get_verifier,
            "has_engine": self.engines.has,
            "list_engines": self.engines.list,
            "register_model": self.plugins.register_model,
            "get_model": self.plugins.get_model,
            "list_models": self.plugins.list_models,
            "get_plugin": self.plugins.get,
            "list_plugins": self.plugins.list,
        }
        if name in delegates:
            return delegates[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def register_plugin(self, plugin: BasePlugin) -> None:
        """Registra un plugin en el catálogo e incorpora en cascada sus modelos, herramientas y motores."""
        self.plugins.register(plugin)
        for m_name, m_cls in plugin.register_models().items():
            self.plugins.register_model(m_name, m_cls)
        for tool in plugin.register_tools():
            self.tools.register(tool)
        for engine in plugin.register_engines().values():
            self.engines.register(engine)

    def get_capabilities_summary(self) -> dict[str, Any]:
        """Genera un resumen estructurado para el endpoint de observabilidad /capabilities."""
        return {
            "plugins_count": len(self.plugins.list()),
            "plugins": [
                {
                    "name": p.name,
                    "version": p.version,
                    "description": p.get_plugin_metadata().description,
                    "tags": p.get_plugin_metadata().tags,
                }
                for p in self.plugins.list()
            ],
            "tools_count": len(self.tools.list()),
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "risk_level": str(t.risk_level),
                    "read_only": t.read_only,
                    "reversible": t.reversible,
                    "makes_http_requests": t.makes_http_requests,
                    "input_schema": _extract_input_schema(t),
                }
                for t in self.tools.list()
            ],
            "engines_count": len(self.engines.list()),
            "engines": [
                {
                    "name": e.name,
                    "engine_type": e.engine_type,
                }
                for e in self.engines.list()
            ],
            "has_observer": self.engines.get_observer() is not None,
            "has_planner": self.engines.get_planner() is not None,
            "has_verifier": self.engines.get_verifier() is not None,
        }

    def clear(self) -> None:
        """Limpia todos los catálogos internos."""
        self.tools.clear()
        self.engines.clear()
        self.plugins.clear()


__all__ = [
    "BootConflictError",
    "CapabilityRegistry",
    "EngineRegistry",
    "PluginCatalog",
    "RISK_WEIGHTS",
    "ToolRegistry",
]
