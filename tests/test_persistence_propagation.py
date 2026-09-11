"""Pruebas unitarias para semántica y propagación de errores en la persistencia de ejecuciones (ISSUE-AGENT-006)."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.executions import (
    _persist_or_update_execution,
    execute_graph_pipeline,
    get_agent_graph,
)
from app.core.checkpointer import get_memory_checkpointer
from app.core.graph import GraphBuilder
from app.core.llm import MockChatModel
from app.core.registry import CapabilityRegistry
from app.db.exceptions import PersistenceError
from app.main import app
from app.models.io import (
    AgentInput,
    AgentOutput,
    ExecutionStatus,
    PersistenceMetadata,
    PersistenceStatus,
)
from app.security.guard import SecurityGuard


@pytest.mark.asyncio
async def test_persist_or_update_execution_success() -> None:
    """Verifica que _persist_or_update_execution persiste y refresca el registro en éxito."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    input_data = AgentInput(
        execution_id="exec-test-persist-01",
        thread_id="thread-test-persist-01",
        prompt="Test persistence success",
    )

    record = await _persist_or_update_execution(
        mock_db,
        input_data=input_data,
        status_val="in_progress",
    )

    assert record is not None
    assert record.execution_id == "exec-test-persist-01"
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    mock_db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_or_update_execution_raises_persistence_error_on_db_failure() -> None:
    """Verifica que _persist_or_update_execution NO silencia excepciones, hace rollback y eleva PersistenceError."""
    mock_db = AsyncMock()
    mock_db.execute.side_effect = OperationalError(
        "connection failure", params=None, orig=Exception("DB Down")
    )

    input_data = AgentInput(
        execution_id="exec-test-persist-err",
        thread_id="thread-test-persist-err",
        prompt="Test persistence failure",
    )

    with pytest.raises(PersistenceError) as exc_info:
        await _persist_or_update_execution(
            mock_db,
            input_data=input_data,
            status_val="in_progress",
        )

    assert "exec-test-persist-err" in str(exc_info.value)
    mock_db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_graph_pipeline_persisted_success() -> None:
    """Verifica que execute_graph_pipeline incluye PersistenceMetadata con status=persisted en éxito."""
    registry = CapabilityRegistry()
    builder = GraphBuilder(
        registry=registry,
        llm=MockChatModel(response_content="Graph execution completed"),
        security_guard=SecurityGuard(),
    )
    graph = builder.build(checkpointer=get_memory_checkpointer())

    input_data = AgentInput(
        execution_id="exec-pipe-success",
        thread_id="thread-pipe-success",
        prompt="Prueba de éxito",
    )

    with patch(
        "app.api.executions._persist_or_update_execution", new_callable=AsyncMock
    ) as mock_persist:
        mock_persist.return_value = MagicMock()
        output = await execute_graph_pipeline(graph, input_data)

    assert isinstance(output, AgentOutput)
    assert output.status == ExecutionStatus.COMPLETED
    assert "persistence" in output.metadata
    meta = PersistenceMetadata(**output.metadata["persistence"])
    assert meta.status == PersistenceStatus.PERSISTED
    assert meta.persisted is True
    assert meta.error is None


@pytest.mark.asyncio
async def test_execute_graph_pipeline_degraded_persistence_propagation() -> None:
    """Verifica que si la persistencia falla en execute_graph_pipeline, se propaga degradación tipada sin tumbar la salida."""
    registry = CapabilityRegistry()
    builder = GraphBuilder(
        registry=registry,
        llm=MockChatModel(response_content="Graph execution completed"),
        security_guard=SecurityGuard(),
    )
    graph = builder.build(checkpointer=get_memory_checkpointer())

    input_data = AgentInput(
        execution_id="exec-pipe-degraded",
        thread_id="thread-pipe-degraded",
        prompt="Prueba de degradación",
    )

    with patch(
        "app.api.executions._persist_or_update_execution",
        side_effect=PersistenceError("Simulated DB storage outage"),
    ):
        output = await execute_graph_pipeline(graph, input_data)

    assert isinstance(output, AgentOutput)
    assert output.status == ExecutionStatus.COMPLETED
    assert "persistence" in output.metadata
    meta = PersistenceMetadata(**output.metadata["persistence"])
    assert meta.status == PersistenceStatus.DEGRADED
    assert meta.persisted is False
    assert "Simulated DB storage outage" in (meta.error or "")
    assert meta.error_type == "PersistenceError"


@pytest.fixture
def client_with_mock_graph() -> Generator[TestClient, None, None]:
    """TestClient configurado con grafo en memoria."""
    builder = GraphBuilder(
        registry=CapabilityRegistry(),
        llm=MockChatModel(response_content="Fast API response"),
        security_guard=SecurityGuard(),
    )
    test_graph = builder.build(checkpointer=get_memory_checkpointer())

    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_trigger_execution_degraded_persistence_initial(client_with_mock_graph: TestClient) -> None:
    """Verifica que POST /executions/trigger maneja fallo inicial de persistencia propagando metadata degradada."""
    payload = {
        "execution_id": "exec-trigger-degraded",
        "thread_id": "thread-trigger-degraded",
        "prompt": "Test trigger degradation",
    }

    with patch(
        "app.api.executions._persist_or_update_execution",
        side_effect=PersistenceError("Failed initial DB registration"),
    ):
        response = client_with_mock_graph.post("/executions/trigger", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["execution_id"] == "exec-trigger-degraded"
    assert "persistence" in data["metadata"]
    assert data["metadata"]["persistence"]["status"] == "degraded"
    assert data["metadata"]["persistence"]["persisted"] is False
    assert "Failed initial DB registration" in data["metadata"]["persistence"]["error"]


@pytest.mark.asyncio
async def test_resolve_hitl_execution_degraded_persistence() -> None:
    """Verifica que _resolve_hitl_execution maneja fallo de persistencia marcando status=degraded."""
    from app.api.executions import _resolve_hitl_execution
    from app.models.io import HITLResolutionRequest

    mock_graph = AsyncMock()
    mock_snapshot = MagicMock()
    mock_snapshot.values = {
        "request": AgentInput(
            execution_id="exec-hitl-01", thread_id="thread-hitl-01", prompt="test"
        ),
        "is_resolved": True,
    }
    mock_snapshot.next = ["human_approval"]
    mock_graph.aget_state.return_value = mock_snapshot

    mock_final_state = {
        "request": AgentInput(
            execution_id="exec-hitl-01", thread_id="thread-hitl-01", prompt="test"
        ),
        "output": AgentOutput(
            execution_id="exec-hitl-01",
            thread_id="thread-hitl-01",
            status=ExecutionStatus.COMPLETED,
            response="Aprobado y ejecutado.",
        ),
    }
    mock_graph.ainvoke.return_value = mock_final_state

    mock_db = AsyncMock()

    with patch(
        "app.api.executions._persist_or_update_execution",
        side_effect=PersistenceError("Fallo en commit final HITL"),
    ):
        output = await _resolve_hitl_execution(
            thread_id="thread-hitl-01",
            approved=True,
            payload=HITLResolutionRequest(approver="supervisor", notes="approved"),
            graph=mock_graph,
            db=mock_db,
        )

    assert output.status == ExecutionStatus.COMPLETED
    assert "persistence" in output.metadata
    assert output.metadata["persistence"]["status"] == "degraded"
    assert output.metadata["persistence"]["persisted"] is False
    assert "Fallo en commit final HITL" in output.metadata["persistence"]["error"]
