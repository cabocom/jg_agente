# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios para la interfaz abstracta BasePlugin, BaseEngine y PluginMetadata."""

import pytest
from jg_sdk.contracts_tools import AgentTool as SDKAgentTool
from pydantic import BaseModel, ValidationError

from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.plugins.base import BaseEngine, BasePlugin, PluginMetadata


class DummyInput(BaseModel):
    query: str


def dummy_func(args: DummyInput) -> ToolResult:
    return ToolResult(success=True, output={"echo": args.query})


class MockEngine(BaseEngine):
    """Engine de prueba concreto."""

    def __init__(self, name: str = "mock_verifier", engine_type: str = "verifier") -> None:
        self._name = name
        self._engine_type = engine_type
        self.started = False
        self.stopped = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def engine_type(self) -> str:
        return self._engine_type

    async def startup(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        self.stopped = True


class MockCustomModel(BaseModel):
    custom_field: str


class ValidPlugin(BasePlugin):
    """Plugin de prueba concreto completamente funcional."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.engine = MockEngine()

    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="test_plugin",
            version="1.2.3",
            description="Plugin de prueba unitaria",
            author="Javier Gálvez",
            jg_agente_version_min="1.0.0",
            tags=["testing", "mock"],
            dependencies=[],
        )

    def register_tools(self) -> list[SDKAgentTool]:
        return [
            AgentTool(
                name="dummy_tool",
                description="Herramienta de prueba",
                category="testing",
                args_schema=DummyInput,
                func=dummy_func,
                risk_level=RiskLevel.LOW,
                required_permissions=["test:read"],
            )
        ]

    def register_engines(self) -> dict[str, BaseEngine]:
        return {"verifier": self.engine}

    def register_models(self) -> dict[str, type[BaseModel]]:
        return {"CustomModel": MockCustomModel}

    async def startup(self) -> None:
        self.started = True
        await self.engine.startup()

    async def shutdown(self) -> None:
        self.stopped = True
        await self.engine.shutdown()


class IncompletePlugin(BasePlugin):
    """Plugin que no implementa los métodos abstractos obligatorios."""

    pass


def test_base_plugin_cannot_be_instantiated_directly() -> None:
    """Verifica que BasePlugin es estrictamente abstracto."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        BasePlugin()  # type: ignore[abstract]

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompletePlugin()  # type: ignore[abstract]


def test_base_engine_cannot_be_instantiated_directly() -> None:
    """Verifica que BaseEngine es estrictamente abstracto."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        BaseEngine()  # type: ignore[abstract]


def test_valid_plugin_contracts() -> None:
    """Verifica la correcta implementación de los contratos de BasePlugin."""
    plugin = ValidPlugin()

    # Metadatos y propiedades de conveniencia
    metadata = plugin.get_plugin_metadata()
    assert metadata.name == "test_plugin"
    assert metadata.version == "1.2.3"
    assert plugin.name == "test_plugin"
    assert plugin.version == "1.2.3"
    assert metadata.description == "Plugin de prueba unitaria"
    assert metadata.author == "Javier Gálvez"
    assert metadata.jg_agente_version_min == "1.0.0"
    assert metadata.enabled is True
    assert metadata.tags == ["testing", "mock"]

    # Registro de tools
    tools = plugin.register_tools()
    assert len(tools) == 1
    assert tools[0].name == "dummy_tool"
    assert tools[0].risk_level == RiskLevel.LOW
    assert tools[0].required_permissions == ["test:read"]

    # Registro de engines
    engines = plugin.register_engines()
    assert "verifier" in engines
    assert engines["verifier"].name == "mock_verifier"
    assert engines["verifier"].engine_type == "verifier"

    # Registro de modelos
    models = plugin.register_models()
    assert "CustomModel" in models
    assert models["CustomModel"] is MockCustomModel


@pytest.mark.asyncio
async def test_plugin_lifecycle_hooks() -> None:
    """Verifica la ejecución de hooks startup, shutdown y health_check."""
    plugin = ValidPlugin()
    assert not plugin.started
    assert not plugin.stopped
    assert not plugin.engine.started
    assert not plugin.engine.stopped

    await plugin.startup()
    assert plugin.started
    assert plugin.engine.started

    health = await plugin.health_check()
    assert health["status"] == "ok"
    assert health["plugin"] == "test_plugin"

    await plugin.shutdown()
    assert plugin.stopped
    assert plugin.engine.stopped


@pytest.mark.asyncio
async def test_plugin_async_context_manager() -> None:
    """Verifica que BasePlugin soporta 'async with' gestionando startup y shutdown."""
    plugin = ValidPlugin()
    assert not plugin.started
    assert not plugin.stopped

    async with plugin as p:
        assert p is plugin
        assert p.started
        assert not p.stopped

    assert plugin.stopped


def test_plugin_metadata_validation() -> None:
    """Verifica validaciones de esquema y restricciones de PluginMetadata."""
    # Nombre normalizado a minúsculas
    meta = PluginMetadata(name="My-Plugin_01", version="1.0.0")
    assert meta.name == "my-plugin_01"

    # Nombre inválido con espacios o caracteres no permitidos
    with pytest.raises(ValidationError):
        PluginMetadata(name="invalid name with spaces", version="1.0.0")

    with pytest.raises(ValidationError):
        PluginMetadata(name="plugin$invalid!", version="1.0.0")

    with pytest.raises(ValidationError):
        PluginMetadata(name="", version="1.0.0")

    # Inmutabilidad (frozen=True)
    with pytest.raises(ValidationError):
        meta.enabled = False

    # Extra fields prohibidos (extra="forbid")
    with pytest.raises(ValidationError):
        PluginMetadata.model_validate(
            {"name": "valid-plugin", "version": "1.0.0", "invalid_attribute": "forbidden"}
        )


def test_default_models_and_engines_default() -> None:
    """Verifica los valores por defecto de métodos opcionales."""

    class MinimalPlugin(BasePlugin):
        def get_plugin_metadata(self) -> PluginMetadata:
            return PluginMetadata(name="minimal-plugin", version="0.1.0")

        def register_tools(self) -> list[SDKAgentTool]:
            return []

        def register_engines(self) -> dict[str, BaseEngine]:
            return {}

    p = MinimalPlugin()
    assert p.register_models() == {}
    assert p.register_tools() == []
    assert p.register_engines() == {}
