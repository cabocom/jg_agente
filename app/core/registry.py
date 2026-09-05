"""Registro central de capacidades (CapabilityRegistry) de jg_agente.

Gestiona la indexación de herramientas (AgentTool), motores de dominio (BaseEngine)
y plugins (BasePlugin) con detección estricta de conflictos en tiempo de arranque.
"""

from typing import Any

from langchain_core.tools import BaseTool
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


class CapabilityRegistry:
    """Catálogo centralizado e inmutable de capacidades en tiempo de ejecución.

    Indexa herramientas únicas por nombre y asegura la unicidad estricta de los
    motores cognitivos singleton (Observer, Planner, Verifier).
    """

    SINGLETON_ENGINE_TYPES: frozenset[str] = frozenset({"observer", "planner", "verifier"})

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}
        self._engines: dict[str, BaseEngine] = {}
        self._singleton_engines: dict[str, BaseEngine] = {}
        self._plugins: dict[str, BasePlugin] = {}
        self._models: dict[str, type[BaseModel]] = {}

    # --- Herramientas (AgentTool) ---

    def register_tool(self, tool: AgentTool) -> None:
        """Registra una herramienta garantizando que su nombre sea único."""
        if tool.name in self._tools:
            raise BootConflictError(
                f"Conflicto en boot: La herramienta '{tool.name}' ya se encuentra registrada en el CapabilityRegistry."
            )
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> AgentTool | None:
        """Obtiene una herramienta por su nombre identificador."""
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Comprueba si existe una herramienta registrada con el nombre dado."""
        return name in self._tools

    def list_tools(
        self,
        category: str | None = None,
        max_risk: RiskLevel | None = None,
    ) -> list[AgentTool]:
        """Lista las herramientas registradas aplicando filtros opcionales de categoría y riesgo máximo."""
        results: list[AgentTool] = []
        max_val = RISK_WEIGHTS.get(max_risk, 4) if max_risk else 4

        for tool in self._tools.values():
            if category and tool.category != category:
                continue
            if RISK_WEIGHTS.get(tool.risk_level, 1) > max_val:
                continue
            results.append(tool)

        return results

    def get_langchain_tools(
        self,
        category: str | None = None,
        max_risk: RiskLevel | None = None,
    ) -> list[BaseTool]:
        """Exporta las herramientas filtradas como instancias nativas BaseTool de LangChain."""
        return [
            t.as_langchain_tool() for t in self.list_tools(category=category, max_risk=max_risk)
        ]

    @property
    def tool_names(self) -> list[str]:
        """Nombres de todas las herramientas registradas."""
        return list(self._tools.keys())

    # --- Motores (BaseEngine) ---

    def register_engine(self, engine: BaseEngine) -> None:
        """Registra un motor de dominio con validación de nombre único y rol cognitivo singleton."""
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

    def get_engine(self, name: str) -> BaseEngine | None:
        """Obtiene un motor por su nombre identificador."""
        return self._engines.get(name)

    def get_engine_by_type(self, engine_type: str) -> BaseEngine | None:
        """Obtiene un motor por su tipo o rol funcional."""
        clean_type = engine_type.lower()
        if clean_type in self._singleton_engines:
            return self._singleton_engines[clean_type]
        for engine in self._engines.values():
            if engine.engine_type.lower() == clean_type:
                return engine
        return None

    def get_observer(self) -> ObserverEngine | BaseEngine | None:
        """Obtiene el ObserverEngine registrado si existe."""
        return self._singleton_engines.get("observer")

    def get_planner(self) -> PlannerEngine | BaseEngine | None:
        """Obtiene el PlannerEngine registrado si existe."""
        return self._singleton_engines.get("planner")

    def get_verifier(self) -> VerifierEngine | BaseEngine | None:
        """Obtiene el VerifierEngine registrado si existe."""
        return self._singleton_engines.get("verifier")

    def has_engine(self, name: str) -> bool:
        """Comprueba si un motor se encuentra registrado por nombre."""
        return name in self._engines

    def list_engines(self) -> list[BaseEngine]:
        """Lista todos los motores registrados."""
        return list(self._engines.values())

    # --- Modelos de Dominio ---

    def register_model(self, name: str, model_cls: type[BaseModel]) -> None:
        """Registra un esquema o modelo Pydantic adicional provisto por un plugin."""
        if name in self._models and self._models[name] is not model_cls:
            raise BootConflictError(
                f"Conflicto en boot: El modelo '{name}' ya se encuentra registrado con una definición distinta."
            )
        self._models[name] = model_cls

    def get_model(self, name: str) -> type[BaseModel] | None:
        """Obtiene un modelo registrado por su nombre."""
        return self._models.get(name)

    def list_models(self) -> dict[str, type[BaseModel]]:
        """Retorna una copia del diccionario de modelos registrados."""
        return dict(self._models)

    # --- Plugins (BasePlugin) ---

    def register_plugin(self, plugin: BasePlugin) -> None:
        """Registra un plugin en el catálogo e incorpora en cascada sus tools, engines y modelos."""
        if plugin.name in self._plugins:
            raise BootConflictError(
                f"Conflicto en boot: El plugin '{plugin.name}' ya se encuentra registrado en el CapabilityRegistry."
            )

        # 1. Registrar modelos
        for m_name, m_cls in plugin.register_models().items():
            self.register_model(m_name, m_cls)

        # 2. Registrar herramientas
        for tool in plugin.register_tools():
            self.register_tool(tool)

        # 3. Registrar motores
        for engine in plugin.register_engines().values():
            self.register_engine(engine)

        self._plugins[plugin.name] = plugin

    def get_plugin(self, name: str) -> BasePlugin | None:
        """Obtiene un plugin registrado por nombre."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[BasePlugin]:
        """Lista todos los plugins registrados."""
        return list(self._plugins.values())

    # --- Resumen e Inspección ---

    def get_capabilities_summary(self) -> dict[str, Any]:
        """Genera un resumen estructurado para el endpoint de observabilidad /capabilities."""
        return {
            "plugins_count": len(self._plugins),
            "plugins": [
                {
                    "name": p.name,
                    "version": p.version,
                    "description": p.get_plugin_metadata().description,
                    "tags": p.get_plugin_metadata().tags,
                }
                for p in self._plugins.values()
            ],
            "tools_count": len(self._tools),
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "risk_level": str(t.risk_level),
                    "read_only": t.read_only,
                    "reversible": t.reversible,
                    "makes_http_requests": t.makes_http_requests,
                }
                for t in self._tools.values()
            ],
            "engines_count": len(self._engines),
            "engines": [
                {
                    "name": e.name,
                    "engine_type": e.engine_type,
                }
                for e in self._engines.values()
            ],
            "has_observer": "observer" in self._singleton_engines,
            "has_planner": "planner" in self._singleton_engines,
            "has_verifier": "verifier" in self._singleton_engines,
        }

    def clear(self) -> None:
        """Limpia todos los catálogos internos (utilizado primordialmente para aislamiento en tests)."""
        self._tools.clear()
        self._engines.clear()
        self._singleton_engines.clear()
        self._plugins.clear()
        self._models.clear()
