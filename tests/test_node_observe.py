# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias e integradas para el nodo opcional de observación (observe_node).

Verifica la invocación polimórfica de ObserverEngine (sync y async), la propagación
de environment_snapshot hacia AgentState, la tolerancia a fallos y la integración
en la topología dinámica de LangGraph.
"""

from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.graph import GraphBuilder
from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import AgentExecutionStatus, AgentState
from app.nodes.observe import observe_node
from app.plugins.base import ObserverEngine

# ==========================================================
# Motores de Prueba Mock
# ==========================================================


class AsyncMockObserver(ObserverEngine):
    """ObserverEngine con método observe asíncrono."""

    @property
    def name(self) -> str:
        return "async_mock_observer"

    async def observe(self, state: AgentState | dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "cluster_status": "healthy",
            "active_nodes": 5,
            "memory_usage_pct": 42.5,
        }


class SyncMockObserver(ObserverEngine):
    """ObserverEngine con método observe síncrono."""

    @property
    def name(self) -> str:
        return "sync_mock_observer"

    def observe(self, state: AgentState | dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "database_connected": True,
            "latency_ms": 1.2,
        }


class ContextAwareObserver(ObserverEngine):
    """ObserverEngine que consume atributos del estado para contextualizar la observación."""

    @property
    def name(self) -> str:
        return "context_aware_observer"

    async def observe(self, state: AgentState | dict[str, Any] | None = None) -> dict[str, Any]:
        req = state.get("request") if state else None
        prompt = getattr(req, "prompt", "") if req else ""
        return {
            "prompt_inspected": prompt,
            "scoped_metric": "custom_val",
        }


class DiscoverObserver(ObserverEngine):
    """ObserverEngine que implementa discover() en lugar de observe()."""

    @property
    def name(self) -> str:
        return "discover_observer"

    async def discover(self) -> dict[str, Any]:
        return {"discovered_assets": ["service_a", "service_b"]}


class FailingObserver(ObserverEngine):
    """ObserverEngine que produce un fallo en runtime."""

    @property
    def name(self) -> str:
        return "failing_observer"

    async def observe(self, state: AgentState | dict[str, Any] | None = None) -> dict[str, Any]:
        raise ConnectionResetError("Conexión perdida con el servicio de telemetría")


# ==========================================================
# Tests Unitarios de observe_node
# ==========================================================


@pytest.mark.asyncio
async def test_observe_node_with_async_engine() -> None:
    """Verifica la ejecución exitosa de observe_node con un ObserverEngine asíncrono."""
    registry = CapabilityRegistry()
    engine = AsyncMockObserver()
    registry.register_engine(engine)

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-obs-01",
            thread_id="thread-obs-01",
            prompt="Verificar estado del cluster",
        ),
        "messages": [HumanMessage(content="Verificar cluster")],
        "status": AgentExecutionStatus.IDLE,
    }

    result = await observe_node(state, registry=registry)

    assert result["status"] == AgentExecutionStatus.OBSERVING
    assert result["environment_snapshot"] == {
        "cluster_status": "healthy",
        "active_nodes": 5,
        "memory_usage_pct": 42.5,
    }
    assert len(result["audit_trail"]) == 1
    audit = result["audit_trail"][0]
    assert audit.event_type == "observe_completed"
    assert audit.actor == "async_mock_observer"
    assert "active_nodes" in audit.details["keys"]
    assert audit.details["duration_ms"] >= 0.0


@pytest.mark.asyncio
async def test_observe_node_with_sync_engine() -> None:
    """Verifica que observe_node soporte funciones observe síncronas."""
    engine = SyncMockObserver()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-obs-02",
            thread_id="thread-obs-02",
            prompt="Check DB latency",
        ),
        "messages": [],
    }

    result = await observe_node(state, engine=engine)

    assert result["status"] == AgentExecutionStatus.OBSERVING
    assert result["environment_snapshot"]["database_connected"] is True
    assert result["environment_snapshot"]["latency_ms"] == 1.2
    assert len(result["audit_trail"]) == 1
    assert result["audit_trail"][0].actor == "sync_mock_observer"


@pytest.mark.asyncio
async def test_observe_node_without_observer() -> None:
    """Verifica que observe_node actúe como no-op seguro si no hay motor registrado."""
    registry = CapabilityRegistry()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-obs-03",
            thread_id="thread-obs-03",
            prompt="Sin observer",
        ),
        "messages": [],
    }

    result = await observe_node(state, registry=registry)

    assert result["status"] == AgentExecutionStatus.OBSERVING
    assert result["environment_snapshot"] == {}
    assert len(result["audit_trail"]) == 1
    audit = result["audit_trail"][0]
    assert audit.details.get("skipped") is True


@pytest.mark.asyncio
async def test_observe_node_passes_state_context() -> None:
    """Verifica que observe_node inyecte el estado como argumento al ObserverEngine."""
    engine = ContextAwareObserver()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-obs-04",
            thread_id="thread-obs-04",
            prompt="Inspección de pods en prod",
        ),
        "messages": [],
    }

    result = await observe_node(state, engine=engine)

    assert result["environment_snapshot"]["prompt_inspected"] == "Inspección de pods en prod"
    assert result["environment_snapshot"]["scoped_metric"] == "custom_val"


@pytest.mark.asyncio
async def test_observe_node_alternative_method_name() -> None:
    """Verifica soporte de métodos alternativos como discover() si no existe observe()."""
    engine = DiscoverObserver()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-obs-05",
            thread_id="thread-obs-05",
            prompt="Descubrimiento de infraestructura",
        ),
        "messages": [],
    }

    result = await observe_node(state, engine=engine)

    assert result["environment_snapshot"] == {
        "discovered_assets": ["service_a", "service_b"],
    }
    assert result["audit_trail"][0].actor == "discover_observer"


@pytest.mark.asyncio
async def test_observe_node_captures_engine_exception() -> None:
    """Verifica contención de excepciones en el motor registrando ExecutionError."""
    engine = FailingObserver()

    state: AgentState = {
        "request": AgentInput(
            execution_id="exec-obs-06",
            thread_id="thread-obs-06",
            prompt="Observación con error",
        ),
        "messages": [],
        "errors": [],
    }

    result = await observe_node(state, engine=engine)

    assert result["status"] == AgentExecutionStatus.OBSERVING
    assert result["environment_snapshot"] == {}
    assert "errors" in result
    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err.code == "OBSERVER_EXECUTION_ERROR"
    assert err.component == "observe"
    assert err.fatal is False
    assert "Conexión perdida" in err.message

    audit = result["audit_trail"][0]
    assert audit.details["has_errors"] is True


# ==========================================================
# Test de Integración con LangGraph compilado
# ==========================================================


@pytest.mark.asyncio
async def test_observe_node_graph_integration() -> None:
    """Verifica la ejecución del nodo observe dentro de un grafo LangGraph compilado."""
    registry = CapabilityRegistry()
    registry.register_engine(AsyncMockObserver())

    builder = GraphBuilder(registry)
    topology = builder.get_topology()
    assert topology.has_observer is True
    assert "observe" in topology.nodes

    graph = builder.build()
    config: RunnableConfig = {"configurable": {"thread_id": "thread-obs-graph-01"}}

    initial_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-obs-graph-01",
            thread_id="thread-obs-graph-01",
            prompt="Estado general del sistema",
        ),
        "messages": [HumanMessage(content="¿Cómo está el sistema?")],
        "status": AgentExecutionStatus.IDLE,
    }

    result = await graph.ainvoke(initial_state, config=config)

    assert result["status"] == AgentExecutionStatus.RESOLVED
    assert result["environment_snapshot"] == {
        "cluster_status": "healthy",
        "active_nodes": 5,
        "memory_usage_pct": 42.5,
    }
    # Validar que el audit_trail contenga el evento observe_completed
    events = [a.event_type for a in result["audit_trail"]]
    assert "observe_completed" in events
    assert "execution_concluded" in events
    # Validar salida canónica AgentOutput
    assert result.get("output") is not None
