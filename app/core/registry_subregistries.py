# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Sub-registros especializados para herramientas, motores y plugins (SOLID/ISP)."""

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from app.models.tools import AgentTool, RiskLevel
from app.plugins.base import (
    BaseEngine,
    BasePlugin,
    ObserverEngine,
    PlannerEngine,
    VerifierEngine,
)


class BootConflictError(Exception):
    """Excepción lanzada cuando ocurre una colisión de capacidades o nombres durante el arranque."""

    pass


RISK_WEIGHTS: dict[RiskLevel, int] = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class ToolRegistry:
    """Sub-registro especializado para la gestión y adaptación de herramientas (AgentTool)."""

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        """Registra una herramienta garantizando unicidad de nombre."""
        if tool.name in self._tools:
            raise BootConflictError(
                f"Conflicto en boot: La herramienta '{tool.name}' ya se encuentra registrada en el CapabilityRegistry."
            )
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool | None:
        """Obtiene una herramienta por nombre."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Comprueba si existe una herramienta registrada por nombre."""
        return name in self._tools

    def list(
        self,
        category: str | None = None,
        max_risk: RiskLevel | None = None,
    ) -> list[AgentTool]:
        """Lista las herramientas registradas aplicando filtros opcionales."""
        max_val = RISK_WEIGHTS.get(max_risk, 4) if max_risk else 4
        return [
            t
            for t in self._tools.values()
            if (not category or t.category == category)
            and (RISK_WEIGHTS.get(t.risk_level, 1) <= max_val)
        ]

    def get_langchain_tools(
        self,
        category: str | None = None,
        max_risk: RiskLevel | None = None,
    ) -> list[BaseTool]:
        """Exporta las herramientas filtradas como instancias nativas BaseTool de LangChain."""
        tools: list[BaseTool] = []
        for t in self.list(category=category, max_risk=max_risk):
            if hasattr(t, "as_langchain_tool") and callable(t.as_langchain_tool):
                tools.append(t.as_langchain_tool())
            else:

                def _wrapper(*args: Any, _tool: Any = t, **kwargs: Any) -> str:
                    return str(_tool.run(*args, **kwargs))

                kw: dict[str, Any] = {
                    "func": _wrapper,
                    "name": t.name,
                    "description": t.description,
                }
                if getattr(t, "args_schema", None) is not None:
                    kw["args_schema"] = t.args_schema
                tools.append(StructuredTool.from_function(**kw))
        return tools

    @property
    def names(self) -> list[str]:
        """Nombres de todas las herramientas registradas."""
        return list(self._tools.keys())

    def clear(self) -> None:
        """Limpia el catálogo de herramientas."""
        self._tools.clear()


class EngineRegistry:
    """Sub-registro especializado para la gestión y unicidad de motores cognitivos."""

    SINGLETON_ENGINE_TYPES: frozenset[str] = frozenset({"observer", "planner", "verifier"})

    def __init__(self) -> None:
        self._engines: dict[str, BaseEngine] = {}
        self._singleton_engines: dict[str, BaseEngine] = {}

    def register(self, engine: BaseEngine) -> None:
        """Registra un motor de dominio con validación de nombre único y rol singleton."""
        if engine.name in self._engines:
            raise BootConflictError(
                f"Conflicto en boot: El motor '{engine.name}' ya se encuentra registrado en el CapabilityRegistry."
            )
        etype = engine.engine_type.lower()
        if etype in self.SINGLETON_ENGINE_TYPES:
            if etype in self._singleton_engines:
                existing = self._singleton_engines[etype]
                raise BootConflictError(
                    f"Conflicto en boot: Ya existe un motor de tipo '{etype}' registrado ('{existing.name}'). "
                    f"No se permite registrar '{engine.name}'."
                )
            self._singleton_engines[etype] = engine
        self._engines[engine.name] = engine

    def get(self, name: str) -> BaseEngine | None:
        """Obtiene un motor por nombre."""
        return self._engines.get(name)

    def get_by_type(self, engine_type: str) -> BaseEngine | None:
        """Obtiene un motor por su tipo o rol funcional."""
        clean_type = engine_type.lower()
        if clean_type in self._singleton_engines:
            return self._singleton_engines[clean_type]
        for engine in self._engines.values():
            if engine.engine_type.lower() == clean_type:
                return engine
        return None

    def get_observer(self) -> ObserverEngine | BaseEngine | None:
        """Obtiene el ObserverEngine singleton registrado."""
        return self._singleton_engines.get("observer")

    def get_planner(self) -> PlannerEngine | BaseEngine | None:
        """Obtiene el PlannerEngine singleton registrado."""
        return self._singleton_engines.get("planner")

    def get_verifier(self) -> VerifierEngine | BaseEngine | None:
        """Obtiene el VerifierEngine singleton registrado."""
        return self._singleton_engines.get("verifier")

    def has(self, name: str) -> bool:
        """Comprueba si un motor se encuentra registrado por nombre."""
        return name in self._engines

    def list(self) -> list[BaseEngine]:
        """Lista todos los motores registrados."""
        return list(self._engines.values())

    def clear(self) -> None:
        """Limpia los motores registrados."""
        self._engines.clear()
        self._singleton_engines.clear()


class PluginCatalog:
    """Sub-catálogo especializado para plugins externos y modelos Pydantic adicionales."""

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}
        self._models: dict[str, type[BaseModel]] = {}

    def register(self, plugin: BasePlugin) -> None:
        """Registra un plugin validando unicidad de nombre."""
        if plugin.name in self._plugins:
            raise BootConflictError(
                f"Conflicto en boot: El plugin '{plugin.name}' ya se encuentra registrado en el CapabilityRegistry."
            )
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> BasePlugin | None:
        """Obtiene un plugin por nombre."""
        return self._plugins.get(name)

    def list(self) -> list[BasePlugin]:
        """Lista todos los plugins registrados."""
        return list(self._plugins.values())

    def register_model(self, name: str, model_cls: type[BaseModel]) -> None:
        """Registra un modelo Pydantic adicional."""
        if name in self._models and self._models[name] is not model_cls:
            raise BootConflictError(
                f"Conflicto en boot: El modelo '{name}' ya se encuentra registrado con una definición distinta."
            )
        self._models[name] = model_cls

    def get_model(self, name: str) -> type[BaseModel] | None:
        """Obtiene un modelo registrado por nombre."""
        return self._models.get(name)

    def list_models(self) -> dict[str, type[BaseModel]]:
        """Retorna una copia de los modelos registrados."""
        return dict(self._models)

    def clear(self) -> None:
        """Limpia plugins y modelos."""
        self._plugins.clear()
        self._models.clear()


__all__ = [
    "BootConflictError",
    "EngineRegistry",
    "PluginCatalog",
    "RISK_WEIGHTS",
    "ToolRegistry",
]
