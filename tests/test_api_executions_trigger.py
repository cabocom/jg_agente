# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.executions import get_agent_graph
from app.core.checkpointer import get_memory_checkpointer
from app.core.graph import GraphBuilder
from app.core.llm import MockChatModel
from app.core.registry import CapabilityRegistry
from app.main import app
from app.models.io import ExecutionStatus
from app.models.tools import AgentTool, RiskLevel
from app.security.guard import SecurityGuard


@pytest.fixture
def mock_registry() -> CapabilityRegistry:
    """Registry con herramientas de prueba de bajo y alto riesgo."""
    reg = CapabilityRegistry()

    def get_info(ip: str = "127.0.0.1") -> str:
        return f"info_{ip}"

    def dangerous_action(target: str) -> str:
        return f"destroyed_{target}"

    reg.register_tool(
        AgentTool(
            name="get_info",
            description="Consulta información de bajo riesgo",
            func=get_info,
            risk_level=RiskLevel.LOW,
            category="diagnostic",
        )
    )
    reg.register_tool(
        AgentTool(
            name="dangerous_action",
            description="Acción peligrosa de alto riesgo",
            func=dangerous_action,
            risk_level=RiskLevel.HIGH,
            category="ops",
        )
    )
    return reg


def make_test_graph(registry: CapabilityRegistry, llm: MockChatModel) -> Any:
    builder = GraphBuilder(
        registry=registry,
        llm=llm,
        security_guard=SecurityGuard(),
    )
    return builder.build(checkpointer=get_memory_checkpointer())


@pytest.fixture
def client(mock_registry: CapabilityRegistry) -> Generator[TestClient, None, None]:
    """TestClient configurado con checkpointer en memoria y registry de test."""
    test_graph = make_test_graph(
        mock_registry,
        MockChatModel(response_content="Mocked response for testing."),
    )

    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_trigger_execution_sync_success(client: TestClient) -> None:
    """Valida ejecución síncrona exitosa devolviendo HTTP 200 y AgentOutput con status=completed."""
    payload = {
        "execution_id": "exec-test-sync-01",
        "thread_id": "thread-test-sync-01",
        "prompt": "Hola, responde directamente sin herramientas",
    }

    response = client.post("/executions/trigger", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["execution_id"] == "exec-test-sync-01"
    assert data["thread_id"] == "thread-test-sync-01"
    assert data["status"] in (ExecutionStatus.COMPLETED.value, "completed")
    assert "response" in data
    assert data["requires_approval"] is False
    assert data["execution_time_ms"] >= 0.0


def test_trigger_execution_with_tool_call(
    client: TestClient, mock_registry: CapabilityRegistry
) -> None:
    """Valida ejecución síncrona con ejecución de herramienta autorizada."""
    llm = MockChatModel(
        tool_calls_to_return=[
            {"id": "call_1", "name": "get_info", "args": {"ip": "10.0.0.1"}, "type": "tool_call"},
        ],
    )
    app.dependency_overrides[get_agent_graph] = lambda: make_test_graph(mock_registry, llm)

    payload = {
        "execution_id": "exec-test-tool-01",
        "thread_id": "thread-test-tool-01",
        "prompt": "Obtener telemetría del nodo",
    }

    response = client.post("/executions/trigger", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["execution_id"] == "exec-test-tool-01"
    assert data["status"] == ExecutionStatus.COMPLETED.value
    assert data["requires_approval"] is False
    assert data["data"] is not None
    assert data["data"]["steps_count"] == 1


def test_trigger_execution_hitl_pause(
    client: TestClient, mock_registry: CapabilityRegistry
) -> None:
    """Valida interrupción HITL ante acción de alto riesgo devolviendo status=waiting_approval."""
    llm = MockChatModel(
        tool_calls_to_return=[
            {
                "id": "call_2",
                "name": "dangerous_action",
                "args": {"target": "prod-cluster"},
                "type": "tool_call",
            },
        ],
    )
    app.dependency_overrides[get_agent_graph] = lambda: make_test_graph(mock_registry, llm)

    payload = {
        "execution_id": "exec-test-hitl-01",
        "thread_id": "thread-test-hitl-01",
        "prompt": "Ejecutar acción destructiva",
    }

    response = client.post("/executions/trigger", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["execution_id"] == "exec-test-hitl-01"
    assert data["status"] == ExecutionStatus.WAITING_APPROVAL.value
    assert data["requires_approval"] is True
    assert data["pending_approval_id"] == "human_approval_required"
    assert "alto riesgo" in data["response"].lower() or "aprobación" in data["response"].lower()


def test_trigger_execution_async_accepted(client: TestClient) -> None:
    """Valida que sync=False responda HTTP 202 Accepted con status=in_progress."""
    payload = {
        "execution_id": "exec-test-async-01",
        "thread_id": "thread-test-async-01",
        "prompt": "Ejecución pesada asíncrona",
    }

    response = client.post("/executions/trigger?sync=false", json=payload)
    assert response.status_code == 202

    data = response.json()
    assert data["execution_id"] == "exec-test-async-01"
    assert data["status"] == ExecutionStatus.IN_PROGRESS.value
    assert "encolada" in data["response"].lower()


def test_trigger_execution_async_parameter_accepted(client: TestClient) -> None:
    """Valida que parameters={'async': True} también active el flujo HTTP 202 Accepted."""
    payload = {
        "execution_id": "exec-test-async-param-01",
        "thread_id": "thread-test-async-param-01",
        "prompt": "Tarea en segundo plano",
        "parameters": {"async": True},
    }

    response = client.post("/executions/trigger", json=payload)
    assert response.status_code == 202

    data = response.json()
    assert data["execution_id"] == "exec-test-async-param-01"
    assert data["status"] == ExecutionStatus.IN_PROGRESS.value


def test_trigger_execution_invalid_payload(client: TestClient) -> None:
    """Valida que un payload con campos faltantes devuelva HTTP 422 Unprocessable Entity."""
    # Falta execution_id y prompt
    payload = {
        "thread_id": "thread-missing-fields",
    }

    response = client.post("/executions/trigger", json=payload)
    assert response.status_code == 422


def test_trigger_execution_uncaught_error_sanitized_response(
    client: TestClient,
) -> None:
    """Valida que excepciones no controladas durante la ejecución no filtren rutas ni datos sensibles [AGENTE-SEC-08]."""
    from unittest.mock import AsyncMock

    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = RuntimeError(
        "Database connection failed to postgresql://admin:secretPass@10.0.1.5:5432/core_db "
        "at /opt/app/core/secret_vault.py line 42"
    )

    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    payload = {
        "execution_id": "exec-uncaught-01",
        "thread_id": "thread-uncaught-01",
        "prompt": "Test uncaught error",
    }

    try:
        response = client.post("/executions/trigger", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["execution_id"] == "exec-uncaught-01"
        assert data["status"] == ExecutionStatus.FAILED.value

        # Verificar que NO se filtre información interna confidencial (CWE-209)
        assert "secretPass" not in data["response"]
        assert "10.0.1.5" not in data["response"]
        assert "/opt/app/core/secret_vault.py" not in data["response"]
        assert "secretPass" not in str(data.get("error", ""))
        assert "10.0.1.5" not in str(data.get("error", ""))

        # Verificar mensaje genérico seguro con ID de incidencia
        assert "ID de incidencia: exec-uncaught-01" in data["response"]
        assert (
            "InternalExecutionError: Incidencia registrada con ID exec-uncaught-01" in data["error"]
        )
    finally:
        app.dependency_overrides.pop(get_agent_graph, None)
