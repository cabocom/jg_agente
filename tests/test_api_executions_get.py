"""Tests de integración para el endpoint GET /executions/{thread_id} en jg_agente."""

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.executions import get_agent_graph
from app.core.graph import GraphBuilder
from app.core.llm import MockChatModel
from app.core.registry import CapabilityRegistry
from app.db.models import CoreExecution
from app.db.session import get_async_session
from app.main import app
from app.models.io import AgentInput, ExecutionStatus
from app.models.state import AgentState, ExecutionError, StepExecutionRecord, StepStatus
from app.models.tools import AgentTool, RiskLevel
from app.security.guard import SecurityGuard


@pytest.fixture
def mock_registry() -> CapabilityRegistry:
    """Registry de prueba con herramientas de bajo y alto riesgo."""
    reg = CapabilityRegistry()

    def get_info(ip: str = "127.0.0.1") -> str:
        return f"info_{ip}"

    def dangerous_action(target: str) -> str:
        return f"destroyed_{target}"

    reg.register_tool(
        AgentTool(
            name="get_info",
            description="Consulta telemetría de bajo riesgo",
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


@pytest.fixture
def shared_checkpointer() -> MemorySaver:
    """Checkpointer persistente en memoria compartido entre invocación y consulta."""
    return MemorySaver()


@pytest.fixture
def client(
    mock_registry: CapabilityRegistry, shared_checkpointer: MemorySaver
) -> Generator[TestClient, None, None]:
    """TestClient configurado con checkpointer compartido y mock graph."""
    builder = GraphBuilder(
        registry=mock_registry,
        llm=MockChatModel(response_content="Ejecución finalizada con éxito."),
        security_guard=SecurityGuard(),
    )
    test_graph = builder.build(checkpointer=shared_checkpointer)

    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_get_execution_not_found(client: TestClient) -> None:
    """Valida que consultar un thread_id inexistente devuelve HTTP 404 Not Found."""
    response = client.get("/executions/thread-inexistente-404")
    assert response.status_code == 404
    data = response.json()
    assert "no encontrado" in data["detail"].lower()


def test_get_execution_completed_success(
    client: TestClient, shared_checkpointer: MemorySaver, mock_registry: CapabilityRegistry
) -> None:
    """Valida que una ejecución completada retorna todos los datos consolidados con HTTP 200."""
    thread_id = "thread-completed-01"
    trigger_payload = {
        "execution_id": "exec-completed-01",
        "thread_id": thread_id,
        "prompt": "Consultar estado del sistema",
    }

    # 1. Disparar ejecución síncrona
    post_resp = client.post("/executions/trigger", json=trigger_payload)
    assert post_resp.status_code == 200

    # 2. Consultar detalle del hilo
    get_resp = client.get(f"/executions/{thread_id}")
    assert get_resp.status_code == 200

    data = get_resp.json()
    assert data["thread_id"] == thread_id
    assert data["execution_id"] == "exec-completed-01"
    assert data["status"] == ExecutionStatus.COMPLETED.value
    assert data["prompt"] == "Consultar estado del sistema"
    assert data["response"] is not None
    assert data["requires_approval"] is False
    assert data["next_nodes"] == []


def test_get_execution_hitl_paused(
    client: TestClient, shared_checkpointer: MemorySaver, mock_registry: CapabilityRegistry
) -> None:
    """Valida consulta de ejecución pausada en HITL devolviendo status=waiting_approval."""
    thread_id = "thread-hitl-paused-01"
    hitl_llm = MockChatModel(
        tool_calls_to_return=[
            {
                "id": "call_hitl",
                "name": "dangerous_action",
                "args": {"target": "cluster-prod"},
                "type": "tool_call",
            }
        ]
    )
    builder = GraphBuilder(
        registry=mock_registry,
        llm=hitl_llm,
        security_guard=SecurityGuard(),
    )
    graph = builder.build(checkpointer=shared_checkpointer)
    app.dependency_overrides[get_agent_graph] = lambda: graph

    trigger_payload = {
        "execution_id": "exec-hitl-01",
        "thread_id": thread_id,
        "prompt": "Destruir cluster",
    }

    # 1. Disparar ejecución que se interrumpe
    post_resp = client.post("/executions/trigger", json=trigger_payload)
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == ExecutionStatus.WAITING_APPROVAL.value

    # 2. Consultar detalle del hilo
    get_resp = client.get(f"/executions/{thread_id}")
    assert get_resp.status_code == 200

    data = get_resp.json()
    assert data["thread_id"] == thread_id
    assert data["execution_id"] == "exec-hitl-01"
    assert data["status"] == ExecutionStatus.WAITING_APPROVAL.value
    assert data["requires_approval"] is True
    assert data["pending_approval_id"] is not None
    assert "human_approval" in data["next_nodes"]


@pytest.mark.asyncio
async def test_get_execution_with_steps_and_errors(
    client: TestClient, shared_checkpointer: MemorySaver, mock_registry: CapabilityRegistry
) -> None:
    """Valida recuperación de pasos ejecutados y errores operacionales desde el checkpoint."""
    thread_id = "thread-errors-steps-01"
    from langchain_core.runnables import RunnableConfig

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    # Inyectar estado directamente en el checkpointer
    initial_state: AgentState = {
        "request": AgentInput(
            execution_id="exec-err-01",
            thread_id=thread_id,
            prompt="Operación con anomalías",
        ),
        "status": "failed",
        "execution_records": [
            StepExecutionRecord(
                step_id="step_01",
                tool_name="get_info",
                tool_args={"ip": "192.168.1.1"},
                status=StepStatus.COMPLETED,
                output="ok",
                duration_ms=12.5,
            )
        ],
        "errors": [
            ExecutionError(
                code="TOOL_TIMEOUT",
                message="Tiempo límite de ejecución superado",
                component="execute",
                fatal=True,
            )
        ],
    }

    builder = GraphBuilder(registry=mock_registry)
    graph = builder.build(checkpointer=shared_checkpointer)
    app.dependency_overrides[get_agent_graph] = lambda: graph

    # Guardar snapshot inicial en el grafo
    await graph.aupdate_state(config, initial_state)

    get_resp = client.get(f"/executions/{thread_id}")
    assert get_resp.status_code == 200

    data = get_resp.json()
    assert data["thread_id"] == thread_id
    assert len(data["steps"]) == 1
    assert data["steps"][0]["tool_name"] == "get_info"
    assert len(data["errors"]) == 1
    assert data["errors"][0]["code"] == "TOOL_TIMEOUT"


def test_get_execution_from_db_when_checkpointer_empty(
    client: TestClient, shared_checkpointer: MemorySaver
) -> None:
    """Valida que si el checkpointer no contiene el hilo, se recupera desde core_executions en BD."""
    thread_id = "thread-db-only-01"

    # Mock de AsyncSession de base de datos
    mock_db = AsyncMock()
    fake_record = CoreExecution(
        execution_id="exec-db-01",
        thread_id=thread_id,
        status="completed",
        prompt="Consulta histórica",
        response="Respuesta histórica desde PostgreSQL",
        parameters={},
        execution_time_ms=45.0,
        requires_approval=False,
        metadata_={"source": "archive"},
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = fake_record
    mock_db.execute.return_value = mock_result

    async def override_get_async_session() -> AsyncGenerator[Any, None]:
        yield mock_db

    app.dependency_overrides[get_async_session] = override_get_async_session

    get_resp = client.get(f"/executions/{thread_id}")
    assert get_resp.status_code == 200

    data = get_resp.json()
    assert data["thread_id"] == thread_id
    assert data["execution_id"] == "exec-db-01"
    assert data["status"] == "completed"
    assert data["prompt"] == "Consulta histórica"
    assert data["response"] == "Respuesta histórica desde PostgreSQL"
    assert data["metadata"] == {"source": "archive"}
