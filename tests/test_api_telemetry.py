# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests exhaustivos para los endpoints de telemetría: /capabilities, /health y /metrics."""

from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from jg_sdk.contracts_tools import AgentTool as SDKAgentTool
from pydantic import BaseModel

from app import __version__
from app.api.telemetry import get_app_registry
from app.core.config import settings
from app.core.registry import CapabilityRegistry
from app.db.session import get_async_session
from app.main import app
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.plugins.base import BaseEngine, BasePlugin, PluginMetadata


class DummyInput(BaseModel):
    query: str


def dummy_tool_func(args: DummyInput) -> ToolResult:
    return ToolResult(success=True, output=f"result_{args.query}")


class SamplePlugin(BasePlugin):
    def get_plugin_metadata(self) -> PluginMetadata:
        return PluginMetadata(name="telemetry_sample_plugin", version="1.0.0")

    def register_tools(self) -> list[SDKAgentTool]:
        return [
            AgentTool(
                name="telemetry_test_tool",
                description="Herramienta para probar telemetría",
                args_schema=DummyInput,
                func=dummy_tool_func,
                risk_level=RiskLevel.LOW,
                category="test",
            )
        ]

    def register_engines(self) -> dict[str, BaseEngine]:
        return {}


@pytest.fixture
def custom_registry() -> CapabilityRegistry:
    """Registry de prueba poblado con plugin y herramienta."""
    registry = CapabilityRegistry()
    plugin = SamplePlugin()
    registry.register_plugin(plugin)
    return registry


@pytest.fixture
def client(custom_registry: CapabilityRegistry) -> Generator[TestClient, None, None]:
    """TestClient con registry inyectado y limpieza de overrides."""
    app.dependency_overrides[get_app_registry] = lambda: custom_registry
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ============================================================================
# Pruebas para GET /capabilities
# ============================================================================


def test_get_capabilities_success(client: TestClient) -> None:
    """Verifica que /capabilities retorna el catálogo estructurado con código HTTP 200."""
    response = client.get("/capabilities")
    assert response.status_code == 200

    data = response.json()
    assert "tools_count" in data
    assert "engines_count" in data
    assert "plugins_count" in data
    assert data["tools_count"] >= 1
    assert data["plugins_count"] >= 1

    # Validar presencia de la herramienta registrada
    tools = data["tools"]
    tool_names = [t["name"] for t in tools]
    assert "telemetry_test_tool" in tool_names

    test_tool_entry = next(t for t in tools if t["name"] == "telemetry_test_tool")
    assert test_tool_entry["description"] == "Herramienta para probar telemetría"
    assert test_tool_entry["risk_level"] == "low"
    assert test_tool_entry["category"] == "test"


# ============================================================================
# Pruebas para GET /health
# ============================================================================


def test_get_health_healthy(client: TestClient) -> None:
    """Verifica que /health retorna 'healthy' cuando la conexión a PostgreSQL responde satisfactoriamente."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_db.execute.return_value = mock_result

    async def override_db() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_async_session] = override_db

    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "jg_agente"
    assert data["version"] == __version__
    assert data["database"] == "connected"
    assert data["database_error"] is None

    # Validar componentes
    components = data["components"]
    assert "database" in components
    assert components["database"]["status"] == "connected"
    assert components["database"]["latency_ms"] is not None
    assert components["database"]["details"]["port"] == 5432

    assert "llm" in components
    assert components["llm"]["status"] == "ready"

    assert "checkpointer" in components
    assert components["checkpointer"]["status"] == "ready"


def test_get_health_unhealthy_on_database_error(client: TestClient) -> None:
    """Verifica que /health retorna HTTP 503 con status 'unhealthy' cuando la BD falla."""
    mock_db = AsyncMock()
    mock_db.execute.side_effect = ConnectionRefusedError("Could not connect to PostgreSQL")

    async def override_db() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_async_session] = override_db

    response = client.get("/health")
    assert response.status_code == 503

    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["database"] == "disconnected"
    assert "Could not connect to PostgreSQL" in str(data["database_error"])
    assert data["components"]["database"]["status"] == "disconnected"


def test_get_health_unhealthy_when_checkpointer_degraded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifica que /health retorna HTTP 503 cuando el checkpointer postgres está degradado."""
    from app.core.checkpointer import get_memory_checkpointer

    monkeypatch.setattr(settings, "CHECKPOINT_SAVER", "postgres")
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    mock_db.execute.return_value = mock_result

    async def override_db() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_async_session] = override_db

    degraded_saver = get_memory_checkpointer()
    setattr(degraded_saver, "is_degraded", True)  # noqa: B010
    setattr(degraded_saver, "degraded_reason", "Connection pool exhausted")  # noqa: B010
    app.state.checkpointer = degraded_saver

    try:
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["components"]["checkpointer"]["status"] == "degraded"
        assert "Connection pool exhausted" in str(data["components"]["checkpointer"]["error"])
    finally:
        app.state.checkpointer = None


# ============================================================================
# Pruebas para GET /metrics
# ============================================================================


def test_get_metrics_aggregated_success(client: TestClient) -> None:
    """Verifica el cálculo y agregación cuantitativa de métricas en /metrics."""
    mock_db = AsyncMock()

    # 1. Mock de consulta de tiempos y totales (COUNT, AVG, MIN, MAX)
    time_row = MagicMock()
    time_row.total = 10
    time_row.avg_time = 145.25
    time_row.min_time = 25.0
    time_row.max_time = 320.50

    time_result = MagicMock()
    time_result.first.return_value = time_row

    # 2. Mock de desglose por estado
    status_result = MagicMock()
    status_result.all.return_value = [
        ("completed", 6),
        ("failed", 2),
        ("cancelled", 1),
        ("waiting_approval", 1),
        ("in_progress", 0),
    ]

    # 3. Mock de conteo HITL
    hitl_result = MagicMock()
    hitl_result.scalar.return_value = 3

    # Configurar respuestas secuenciales de mock_db.execute
    mock_db.execute.side_effect = [time_result, status_result, hitl_result]

    async def override_db() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_async_session] = override_db

    response = client.get("/metrics")
    assert response.status_code == 200

    data = response.json()
    assert data["service"] == "jg_agente"
    assert data["version"] == __version__
    assert data["uptime_seconds"] >= 0.0

    # Validar bloque de ejecuciones
    execs = data["executions"]
    assert execs["total_executions"] == 10
    assert execs["completed"] == 6
    assert execs["failed"] == 2
    assert execs["cancelled"] == 1
    assert execs["waiting_approval"] == 1
    assert execs["in_progress"] == 0
    assert execs["avg_execution_time_ms"] == 145.25
    assert execs["min_execution_time_ms"] == 25.0
    assert execs["max_execution_time_ms"] == 320.50

    # Validar bloque de HITL
    hitl = data["hitl"]
    assert hitl["approvals_requested"] == 3
    assert hitl["approvals_pending"] == 1

    # Validar capacidades registradas
    caps = data["capabilities"]
    assert caps["tools_count"] >= 1
    assert caps["plugins_count"] >= 1


def test_get_metrics_resilience_on_database_error(client: TestClient) -> None:
    """Verifica que /metrics responde de forma tolerante y resiliente si la base de datos no está disponible."""
    mock_db = AsyncMock()
    mock_db.execute.side_effect = RuntimeError("Base de datos no accesible")

    async def override_db() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_async_session] = override_db

    response = client.get("/metrics")
    assert response.status_code == 200

    data = response.json()
    assert data["service"] == "jg_agente"
    assert data["executions"]["total_executions"] == 0
    assert data["executions"]["avg_execution_time_ms"] == 0.0
    assert data["hitl"]["approvals_requested"] == 0
    assert data["hitl"]["approvals_pending"] == 0
