"""Tests unitarios para CapabilityRegistry y detección estricta de conflictos de arranque."""

import pytest
from pydantic import BaseModel

from app.core.registry import BootConflictError, CapabilityRegistry
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.plugins.base import (
    BaseEngine,
    BasePlugin,
    ObserverEngine,
    PlannerEngine,
    PluginMetadata,
    VerifierEngine,
)

# --- Modelos y funciones dummy ---


class SampleInput(BaseModel):
    param: str


def sample_func(args: SampleInput) -> ToolResult:
    return ToolResult(success=True, output={"echo": args.param})


def make_tool(
    name: str, category: str = "general", risk_level: RiskLevel = RiskLevel.LOW
) -> AgentTool:
    return AgentTool(
        name=name,
        description=f"Herramienta {name}",
        category=category,
        args_schema=SampleInput,
        func=sample_func,
        risk_level=risk_level,
    )


# --- Motores dummy ---


class MockPlannerA(PlannerEngine):
    @property
    def name(self) -> str:
        return "planner_a"


class MockPlannerB(PlannerEngine):
    @property
    def name(self) -> str:
        return "planner_b"


class MockObserver(ObserverEngine):
    @property
    def name(self) -> str:
        return "observer_primary"


class MockVerifier(VerifierEngine):
    @property
    def name(self) -> str:
        return "verifier_primary"


class MockDiscoveryEngine(BaseEngine):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def engine_type(self) -> str:
        return "discovery"


# --- Tests de Herramientas ---


def test_register_and_query_tools() -> None:
    """Verifica el registro y consulta de herramientas por nombre y filtros."""
    registry = CapabilityRegistry()
    tool1 = make_tool("read_status", category="monitoring", risk_level=RiskLevel.LOW)
    tool2 = make_tool("restart_service", category="maintenance", risk_level=RiskLevel.HIGH)

    registry.register_tool(tool1)
    registry.register_tool(tool2)

    assert registry.has_tool("read_status")
    assert registry.has_tool("restart_service")
    assert not registry.has_tool("unknown_tool")

    assert registry.get_tool("read_status") is tool1
    assert registry.get_tool("restart_service") is tool2
    assert sorted(registry.tool_names) == ["read_status", "restart_service"]

    # Filtros por categoría
    monitoring_tools = registry.list_tools(category="monitoring")
    assert len(monitoring_tools) == 1
    assert monitoring_tools[0].name == "read_status"

    # Filtros por riesgo máximo
    low_risk = registry.list_tools(max_risk=RiskLevel.LOW)
    assert len(low_risk) == 1
    assert low_risk[0].name == "read_status"

    all_risk = registry.list_tools(max_risk=RiskLevel.HIGH)
    assert len(all_risk) == 2


def test_tool_duplicate_name_raises_boot_conflict_error() -> None:
    """Verifica que registrar dos tools con el mismo nombre lanza BootConflictError."""
    registry = CapabilityRegistry()
    t1 = make_tool("duplicate_tool", category="a")
    t2 = make_tool("duplicate_tool", category="b")

    registry.register_tool(t1)

    with pytest.raises(BootConflictError, match="ya se encuentra registrada"):
        registry.register_tool(t2)


def test_get_langchain_tools() -> None:
    """Verifica la exportación a herramientas nativas de LangChain."""
    registry = CapabilityRegistry()
    tool = make_tool("diagnostic_tool", category="diagnostics")
    registry.register_tool(tool)

    lc_tools = registry.get_langchain_tools()
    assert len(lc_tools) == 1
    assert lc_tools[0].name == "diagnostic_tool"


# --- Tests de Motores y Reglas Singleton ---


def test_register_engines_and_singleton_access() -> None:
    """Verifica el registro exitoso de motores cognitivos."""
    registry = CapabilityRegistry()
    planner = MockPlannerA()
    observer = MockObserver()
    verifier = MockVerifier()

    registry.register_engine(planner)
    registry.register_engine(observer)
    registry.register_engine(verifier)

    assert registry.get_planner() is planner
    assert registry.get_observer() is observer
    assert registry.get_verifier() is verifier

    assert registry.get_engine("planner_a") is planner
    assert registry.get_engine_by_type("planner") is planner
    assert registry.get_engine_by_type("observer") is observer
    assert registry.get_engine_by_type("verifier") is verifier
    assert len(registry.list_engines()) == 3


def test_two_planners_raise_boot_conflict_error() -> None:
    """Criterio de Aceptación: Intentar registrar dos PlannerEngine distintos lanza BootConflictError."""
    registry = CapabilityRegistry()
    planner_a = MockPlannerA()
    planner_b = MockPlannerB()

    registry.register_engine(planner_a)

    with pytest.raises(BootConflictError, match="Ya existe un motor de tipo 'planner' registrado"):
        registry.register_engine(planner_b)


def test_two_observers_or_verifiers_raise_boot_conflict_error() -> None:
    """Verifica que observer y verifier también cumplen la regla de rol único."""
    registry = CapabilityRegistry()
    obs1 = MockObserver()

    class AnotherObserver(ObserverEngine):
        @property
        def name(self) -> str:
            return "observer_secondary"

    registry.register_engine(obs1)
    with pytest.raises(BootConflictError, match="Ya existe un motor de tipo 'observer' registrado"):
        registry.register_engine(AnotherObserver())

    ver1 = MockVerifier()

    class AnotherVerifier(VerifierEngine):
        @property
        def name(self) -> str:
            return "verifier_secondary"

    registry.register_engine(ver1)
    with pytest.raises(BootConflictError, match="Ya existe un motor de tipo 'verifier' registrado"):
        registry.register_engine(AnotherVerifier())


def test_custom_engines_allow_multiple_with_unique_names() -> None:
    """Verifica que motores no singleton pueden coexistir si sus nombres son únicos."""
    registry = CapabilityRegistry()
    e1 = MockDiscoveryEngine("docker_discovery")
    e2 = MockDiscoveryEngine("k8s_discovery")

    registry.register_engine(e1)
    registry.register_engine(e2)

    assert registry.has_engine("docker_discovery")
    assert registry.has_engine("k8s_discovery")

    # Si intentamos registrar otro con el mismo nombre, falla
    e3 = MockDiscoveryEngine("docker_discovery")
    with pytest.raises(BootConflictError, match="ya se encuentra registrado"):
        registry.register_engine(e3)


# --- Tests de Plugins en Cascada ---


class SamplePluginModel(BaseModel):
    data: str


class SamplePlugin(BasePlugin):
    def __init__(self, name: str = "sample-plugin") -> None:
        self._name = name

    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(name=self._name, version="1.0.0", description="Plugin de prueba")

    def register_tools(self) -> list[AgentTool]:
        return [make_tool(f"{self._name}_tool")]

    def register_engines(self) -> dict[str, BaseEngine]:
        return {"discovery": MockDiscoveryEngine(f"{self._name}_discovery")}

    def register_models(self) -> dict[str, type[BaseModel]]:
        return {"SampleModel": SamplePluginModel}


def test_register_plugin_cascades_components() -> None:
    """Verifica que registrar un plugin incorpora sus tools, engines y modelos."""
    registry = CapabilityRegistry()
    plugin = SamplePlugin("devops-core")

    registry.register_plugin(plugin)

    assert registry.get_plugin("devops-core") is plugin
    assert registry.has_tool("devops-core_tool")
    assert registry.has_engine("devops-core_discovery")
    assert registry.get_model("SampleModel") is SamplePluginModel

    # Registrar el mismo plugin dos veces lanza error
    with pytest.raises(BootConflictError, match="ya se encuentra registrado"):
        registry.register_plugin(plugin)


def test_register_plugin_propagates_tool_conflict() -> None:
    """Verifica que un conflicto de tool en un plugin aborta el registro."""
    registry = CapabilityRegistry()
    registry.register_tool(make_tool("conflicting_tool"))

    class ConflictingPlugin(BasePlugin):
        def get_plugin_metadata(self) -> PluginMetadata:
            return PluginMetadata(name="bad-plugin", version="1.0.0")

        def register_tools(self) -> list[AgentTool]:
            return [make_tool("conflicting_tool")]

        def register_engines(self) -> dict[str, BaseEngine]:
            return {}

    with pytest.raises(BootConflictError, match="conflicting_tool"):
        registry.register_plugin(ConflictingPlugin())


# --- Resumen y Limpieza ---


def test_capabilities_summary_and_clear() -> None:
    """Verifica la estructura de resumen para /capabilities y la limpieza total."""
    registry = CapabilityRegistry()
    plugin = SamplePlugin("monitoring")
    registry.register_plugin(plugin)
    registry.register_engine(MockPlannerA())

    summary = registry.get_capabilities_summary()
    assert summary["plugins_count"] == 1
    assert summary["tools_count"] == 1
    assert summary["engines_count"] == 2  # discovery + planner
    assert summary["has_planner"] is True
    assert summary["has_observer"] is False
    assert summary["has_verifier"] is False

    registry.clear()
    assert len(registry.list_tools()) == 0
    assert len(registry.list_engines()) == 0
    assert len(registry.list_plugins()) == 0
    assert len(registry.list_models()) == 0
