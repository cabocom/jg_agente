# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios e integración para la validación de integridad en boot del agente."""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jg_sdk.contracts_tools import AgentTool as SDKAgentTool
from pydantic import BaseModel

from app.core.boot import (
    BootIntegrityError,
    init_agent_capabilities,
    validate_boot_capabilities,
)
from app.core.config import Settings
from app.core.plugin_manager import PluginManager
from app.core.registry import BootConflictError, CapabilityRegistry
from app.main import app
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.plugins.base import (
    BaseEngine,
    BasePlugin,
    ObserverEngine,
    PlannerEngine,
    PluginMetadata,
    VerifierEngine,
)


class DummyInput(BaseModel):
    text: str


def dummy_func(args: DummyInput) -> ToolResult:
    return ToolResult(success=True, output=args.text)


def make_test_tool(name: str) -> AgentTool:
    return AgentTool(
        name=name,
        description=f"Herramienta {name}",
        category="testing",
        args_schema=DummyInput,
        func=dummy_func,
        risk_level=RiskLevel.LOW,
    )


class SamplePlugin(BasePlugin):
    def __init__(self, name: str = "essential_plugin") -> None:
        self._name = name

    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(name=self._name, version="1.0.0", description="Plugin esencial")

    def register_tools(self) -> list[SDKAgentTool]:
        return [make_test_tool(f"{self._name}_tool")]

    def register_engines(self) -> dict[str, BaseEngine]:
        return {}


class SamplePlanner(PlannerEngine):
    @property
    def name(self) -> str:
        return "sample_planner"


class SampleObserver(ObserverEngine):
    @property
    def name(self) -> str:
        return "sample_observer"


class SampleVerifier(VerifierEngine):
    @property
    def name(self) -> str:
        return "sample_verifier"


# --- Tests de validate_boot_capabilities ---


def test_validate_boot_capabilities_success() -> None:
    """Verifica que la validación tiene éxito cuando todas las capacidades requeridas están presentes."""
    registry = CapabilityRegistry()
    registry.register_plugin(SamplePlugin("core_plugin"))
    registry.register_tool(make_test_tool("required_tool"))
    registry.register_engine(SamplePlanner())
    registry.register_engine(SampleObserver())
    registry.register_engine(SampleVerifier())

    # No debe lanzar excepción
    validate_boot_capabilities(
        registry=registry,
        required_plugins=["core_plugin"],
        required_tools=["required_tool", "core_plugin_tool"],
        require_planner=True,
        require_observer=True,
        require_verifier=True,
    )


def test_missing_required_plugin_raises_boot_integrity_error() -> None:
    """Verifica que la ausencia de un plugin esencial lanza BootIntegrityError descriptivo."""
    registry = CapabilityRegistry()
    with pytest.raises(
        BootIntegrityError, match="plugins esenciales no se encuentran registrados: missing_plugin"
    ):
        validate_boot_capabilities(registry=registry, required_plugins=["missing_plugin"])


def test_missing_required_tool_raises_boot_integrity_error() -> None:
    """Verifica que la ausencia de una herramienta esencial lanza BootIntegrityError descriptivo."""
    registry = CapabilityRegistry()
    with pytest.raises(
        BootIntegrityError,
        match="herramientas esenciales no se encuentran registradas: missing_tool",
    ):
        validate_boot_capabilities(registry=registry, required_tools=["missing_tool"])


def test_missing_required_planner_raises_boot_integrity_error() -> None:
    """Verifica que el perfil que exige PlannerEngine falla si no hay uno registrado."""
    registry = CapabilityRegistry()
    with pytest.raises(BootIntegrityError, match="exige un PlannerEngine registrado"):
        validate_boot_capabilities(registry=registry, require_planner=True)


def test_missing_required_observer_raises_boot_integrity_error() -> None:
    """Verifica que el perfil que exige ObserverEngine falla si no hay uno registrado."""
    registry = CapabilityRegistry()
    with pytest.raises(BootIntegrityError, match="exige un ObserverEngine registrado"):
        validate_boot_capabilities(registry=registry, require_observer=True)


def test_missing_required_verifier_raises_boot_integrity_error() -> None:
    """Verifica que el perfil que exige VerifierEngine falla si no hay uno registrado."""
    registry = CapabilityRegistry()
    with pytest.raises(BootIntegrityError, match="exige un VerifierEngine registrado"):
        validate_boot_capabilities(registry=registry, require_verifier=True)


def test_tool_invalid_func_raises_boot_integrity_error() -> None:
    """Verifica que herramientas con func no ejecutable o vacía lanzan BootIntegrityError."""
    registry = CapabilityRegistry()
    tool = make_test_tool("corrupt_tool")
    tool.func = "not_callable"  # type: ignore[assignment]
    registry.register_tool(tool)

    with pytest.raises(BootIntegrityError, match="no define una función ejecutable callable"):
        validate_boot_capabilities(registry=registry)


# --- Tests de init_agent_capabilities ---


def test_init_agent_capabilities_success() -> None:
    """Verifica que init_agent_capabilities inicializa registro y gestor limpiamente."""
    custom_settings = Settings(REQUIRED_PLUGINS=[], REQUIRED_TOOLS=[])
    reg, pm = init_agent_capabilities(cfg=custom_settings)
    assert isinstance(reg, CapabilityRegistry)
    assert isinstance(pm, PluginManager)


def test_init_agent_capabilities_propagates_conflict_error() -> None:
    """Verifica que colisiones durante la carga de plugins propagan BootConflictError."""

    class ClashingPlanner(PlannerEngine):
        @property
        def name(self) -> str:
            return "planner_clash"

    class ClashingPlugin(BasePlugin):
        def get_plugin_metadata(self) -> PluginMetadata:
            return PluginMetadata(name="clash_plugin", version="1.0.0")

        def register_tools(self) -> list[SDKAgentTool]:
            return []

        def register_engines(self) -> dict[str, BaseEngine]:
            return {"planner": ClashingPlanner()}

    reg = CapabilityRegistry()
    reg.register_engine(SamplePlanner())  # Ya existe un planner en registry

    pm = PluginManager(registry=reg)
    with (
        patch.object(pm, "discover_local_plugins", return_value=[ClashingPlugin]),
        patch.object(pm, "discover_entrypoints", return_value=[]),
        pytest.raises(BootConflictError, match="Ya existe un motor de tipo 'planner'"),
    ):
        init_agent_capabilities(registry=reg, plugin_manager=pm)


# --- Tests de FastAPI Lifespan y Endpoint /capabilities ---


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def test_get_capabilities_endpoint(client: TestClient) -> None:
    """Verifica que el endpoint GET /capabilities responde con el catálogo activo."""
    response = client.get("/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "tools_count" in data
    assert "engines_count" in data
    assert "plugins_count" in data
    assert "tools" in data
    assert "plugins" in data
    assert "engines" in data


def test_fastapi_lifespan_aborts_on_missing_required_capability() -> None:
    """Verifica que FastAPI aborta el arranque si la configuración exige una capacidad ausente."""
    strict_settings = Settings(REQUIRED_PLUGINS=["mandatory_but_missing_plugin"])

    with (
        patch("app.main.settings", strict_settings),
        pytest.raises(BootIntegrityError, match="mandatory_but_missing_plugin"),
        TestClient(app),
    ):
        pass
