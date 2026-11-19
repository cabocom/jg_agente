# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios para PluginManager, autodescubrimiento y resolución de dependencias."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from jg_sdk.contracts_tools import AgentTool as SDKAgentTool
from pydantic import BaseModel

from app.core.plugin_manager import (
    PluginDependencyError,
    PluginLoadError,
    PluginManager,
)
from app.core.registry import CapabilityRegistry
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.plugins.base import (
    BaseEngine,
    BasePlugin,
    PluginMetadata,
)


class SimpleInput(BaseModel):
    val: str


def simple_func(args: SimpleInput) -> ToolResult:
    return ToolResult(success=True, output=args.val)


class MockPluginA(BasePlugin):
    """Plugin A sin dependencias."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(name="plugin_a", version="1.0.0", description="Plugin A base")

    def register_tools(self) -> list[SDKAgentTool]:
        return [
            AgentTool(
                name="tool_a",
                description="Herramienta de Plugin A",
                category="test",
                args_schema=SimpleInput,
                func=simple_func,
                risk_level=RiskLevel.LOW,
            )
        ]

    def register_engines(self) -> dict[str, BaseEngine]:
        return {}

    async def startup(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        self.stopped = True


class MockPluginB(BasePlugin):
    """Plugin B que depende de Plugin A."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="plugin_b",
            version="1.0.0",
            description="Plugin B dependiente",
            dependencies=["plugin_a"],
        )

    def register_tools(self) -> list[SDKAgentTool]:
        return [
            AgentTool(
                name="tool_b",
                description="Herramienta de Plugin B",
                category="test",
                args_schema=SimpleInput,
                func=simple_func,
                risk_level=RiskLevel.LOW,
            )
        ]

    def register_engines(self) -> dict[str, BaseEngine]:
        return {}

    async def startup(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        self.stopped = True


class InvalidPlugin:
    """Clase no heredera de BasePlugin."""

    pass


# --- Tests de Registro Manual e Integración con Registry ---


def test_manual_registration_and_registry_integration() -> None:
    """Verifica el registro de instancias y su propagación al CapabilityRegistry."""
    registry = CapabilityRegistry()
    pm = PluginManager(registry=registry)

    plugin_a = MockPluginA()
    plugin_b = MockPluginB()

    pm.register_plugin_instance(plugin_a)
    pm.register_plugin_instance(plugin_b)

    assert "plugin_a" in pm.loaded_plugins
    assert "plugin_b" in pm.loaded_plugins

    # Las herramientas deben estar presentes en el registry
    assert registry.has_tool("tool_a")
    assert registry.has_tool("tool_b")

    # El orden topológico debe ubicar 'plugin_a' antes que 'plugin_b'
    order = pm._resolve_dependencies_and_order()
    assert order == ["plugin_a", "plugin_b"]


def test_register_invalid_instance_raises_plugin_load_error() -> None:
    """Verifica que intentar registrar un objeto que no es BasePlugin lanza PluginLoadError."""
    pm = PluginManager()
    with pytest.raises(PluginLoadError, match="no es una instancia de BasePlugin"):
        pm.register_plugin_instance(InvalidPlugin())  # type: ignore[arg-type]


# --- Tests de Dependencias (Ausentes y Circulares) ---


def test_missing_dependency_raises_plugin_dependency_error() -> None:
    """Verifica que una dependencia ausente aborta la carga con PluginDependencyError."""
    pm = PluginManager()
    plugin_b = MockPluginB()  # Requiere 'plugin_a'
    pm.register_plugin_instance(plugin_b)

    with pytest.raises(PluginDependencyError, match="requiere el plugin 'plugin_a'"):
        pm._resolve_dependencies_and_order()


def test_circular_dependency_raises_plugin_dependency_error() -> None:
    """Verifica que dependencias circulares son detectadas y abortadas."""

    class CircularPluginX(BasePlugin):
        def get_plugin_metadata(self) -> PluginMetadata:
            return PluginMetadata(name="plugin_x", version="1.0.0", dependencies=["plugin_y"])

        def register_tools(self) -> list[SDKAgentTool]:
            return []

        def register_engines(self) -> dict[str, BaseEngine]:
            return {}

    class CircularPluginY(BasePlugin):
        def get_plugin_metadata(self) -> PluginMetadata:
            return PluginMetadata(name="plugin_y", version="1.0.0", dependencies=["plugin_x"])

        def register_tools(self) -> list[SDKAgentTool]:
            return []

        def register_engines(self) -> dict[str, BaseEngine]:
            return {}

    pm = PluginManager()
    pm.register_plugin_instance(CircularPluginX())
    pm.register_plugin_instance(CircularPluginY())

    with pytest.raises(PluginDependencyError, match="Dependencia circular detectada"):
        pm._resolve_dependencies_and_order()


# --- Tests de Ciclo de Vida Asíncrono y Orden ---


@pytest.mark.asyncio
async def test_lifecycle_startup_and_shutdown_order() -> None:
    """Verifica que startup se ejecuta en orden de dependencias y shutdown en orden inverso."""
    events: list[str] = []

    class OrderA(MockPluginA):
        async def startup(self) -> None:
            events.append("startup_a")

        async def shutdown(self) -> None:
            events.append("shutdown_a")

    class OrderB(MockPluginB):
        async def startup(self) -> None:
            events.append("startup_b")

        async def shutdown(self) -> None:
            events.append("shutdown_b")

    pm = PluginManager()
    pm.register_plugin_instance(OrderB())
    pm.register_plugin_instance(OrderA())

    async with pm:
        # startup() debe haber ejecutado 'a' antes que 'b'
        assert events == ["startup_a", "startup_b"]

    # shutdown() debe haber ejecutado 'b' antes que 'a'
    assert events == ["startup_a", "startup_b", "shutdown_b", "shutdown_a"]


@pytest.mark.asyncio
async def test_health_check_aggregation() -> None:
    """Verifica que health_check consolida los reportes de todos los plugins."""
    pm = PluginManager()
    pm.register_plugin_instance(MockPluginA())
    pm.register_plugin_instance(MockPluginB())

    health = await pm.health_check()
    assert health["status"] == "ok"
    assert health["plugins_count"] == 2
    assert "plugin_a" in health["plugins"]
    assert "plugin_b" in health["plugins"]


# --- Tests de Autodescubrimiento Vía Entry Points ---


def test_discover_entrypoints_success() -> None:
    """Verifica el descubrimiento mediante entry_points simulados."""
    mock_ep = MagicMock()
    mock_ep.name = "plugin_a"
    mock_ep.load.return_value = MockPluginA

    with patch("app.core.plugin_manager.entry_points", return_value=[mock_ep]):
        pm = PluginManager()
        discovered = pm.discover_entrypoints(group="jg_agente.plugins")
        assert len(discovered) == 1
        assert discovered[0] is MockPluginA


def test_discover_entrypoints_invalid_class_raises_error() -> None:
    """Verifica que un entry point apuntando a un objeto inválido lanza PluginLoadError."""
    mock_ep = MagicMock()
    mock_ep.name = "invalid_ep"
    mock_ep.load.return_value = InvalidPlugin

    with patch("app.core.plugin_manager.entry_points", return_value=[mock_ep]):
        pm = PluginManager()
        with pytest.raises(
            PluginLoadError, match="no referencia una subclase válida de BasePlugin"
        ):
            pm.discover_entrypoints()


# --- Tests de Autodescubrimiento Local con Directorio Temporal ---


def test_discover_local_plugins_with_plugin_class(tmp_path: Path) -> None:
    """Verifica el descubrimiento local en carpeta con estructura plugin.py y PLUGIN_CLASS."""
    plugin_dir = tmp_path / "sample_local"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

    plugin_code = """
from app.plugins.base import BaseEngine, BasePlugin, PluginMetadata
from jg_sdk.contracts_tools import AgentTool

class LocalPlugin(BasePlugin):
    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(name="local_sample", version="1.0.0", description="Local plugin")

    def register_tools(self) -> list[AgentTool]:
        return []

    def register_engines(self) -> dict[str, BaseEngine]:
        return {}

PLUGIN_CLASS = LocalPlugin
"""
    (plugin_dir / "plugin.py").write_text(plugin_code, encoding="utf-8")

    registry = CapabilityRegistry()
    pm = PluginManager(registry=registry)
    loaded = pm.load_plugins(plugins_dir=tmp_path, load_entrypoints=False, load_local=True)

    assert len(loaded) == 1
    assert loaded[0].name == "local_sample"
    assert "local_sample" in pm.loaded_plugins
    assert registry.get_plugin("local_sample") is not None


def test_plugin_manager_filters_by_enabled_plugins(tmp_path: Path) -> None:
    """Verifica que PluginManager filtra y solo carga los plugins declarados en enabled_plugins."""
    # Crear plugin A
    dir_a = tmp_path / "pkg_a"
    dir_a.mkdir()
    (dir_a / "__init__.py").write_text("", encoding="utf-8")
    (dir_a / "plugin.py").write_text(
        """
from app.plugins.base import BasePlugin, PluginMetadata

class PluginA(BasePlugin):
    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(name="plugin_a", version="0.1.0", description="A", author="Test")
    def register_tools(self): return []
    def register_engines(self): return {}
PLUGIN_CLASS = PluginA
""",
        encoding="utf-8",
    )

    # Crear plugin B
    dir_b = tmp_path / "pkg_b"
    dir_b.mkdir()
    (dir_b / "__init__.py").write_text("", encoding="utf-8")
    (dir_b / "plugin.py").write_text(
        """
from app.plugins.base import BasePlugin, PluginMetadata

class PluginB(BasePlugin):
    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(name="plugin_b", version="0.1.0", description="B", author="Test")
    def register_tools(self): return []
    def register_engines(self): return {}
PLUGIN_CLASS = PluginB
""",
        encoding="utf-8",
    )

    # Caso 1: Habilitar solo plugin_a por nombre
    reg1 = CapabilityRegistry()
    pm1 = PluginManager(registry=reg1, enabled_plugins=["plugin_a"])
    loaded1 = pm1.load_plugins(plugins_dir=tmp_path, load_entrypoints=False, load_local=True)
    assert len(loaded1) == 1
    assert loaded1[0].name == "plugin_a"
    assert "plugin_b" not in pm1.loaded_plugins

    # Caso 2: Habilitar solo pkg_b por nombre de módulo string separado por comas
    reg2 = CapabilityRegistry()
    pm2 = PluginManager(registry=reg2, enabled_plugins="pkg_b")
    loaded2 = pm2.load_plugins(plugins_dir=tmp_path, load_entrypoints=False, load_local=True)
    assert len(loaded2) == 1
    assert loaded2[0].name == "plugin_b"
    assert "plugin_a" not in pm2.loaded_plugins
