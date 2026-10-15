# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias para resiliencia, reintentos y propagación de errores en persistencia (AGENTE-STATE-01)."""

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.executions import (
    _persist_or_update_execution,
    _persist_with_retry,
    _spool_emergency_execution,
    execute_graph_pipeline,
    get_agent_graph,
)
from app.core.checkpointer import get_memory_checkpointer
from app.core.config import settings
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
async def test_persist_with_retry_transient_failure_recovery() -> None:
    """Verifica que _persist_with_retry reintente y tenga éxito si el fallo de DB es transitorio."""
    input_data = AgentInput(
        execution_id="exec-retry-transient",
        thread_id="thread-retry-transient",
        prompt="Test transient recovery",
    )

    call_count = 0

    async def mock_persist_call(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise PersistenceError("Transient DB glitch")
        record = MagicMock()
        record.execution_id = "exec-retry-transient"
        return record

    with patch("app.api.executions._persist_or_update_execution", side_effect=mock_persist_call):
        record = await _persist_with_retry(
            input_data=input_data,
            status_val="completed",
            max_retries=3,
            backoff_base=0.01,
        )

    assert record.execution_id == "exec-retry-transient"
    assert call_count == 2


@pytest.mark.asyncio
async def test_persist_with_retry_fatal_failure_raises_persistence_error() -> None:
    """Verifica que _persist_with_retry agote los reintentos y eleve PersistenceError si la DB sigue caída."""
    input_data = AgentInput(
        execution_id="exec-retry-fatal",
        thread_id="thread-retry-fatal",
        prompt="Test fatal outage",
    )

    call_count = 0

    async def mock_persist_always_fails(*args: Any, **kwargs: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        raise PersistenceError("Persistent DB outage")

    with (
        patch(
            "app.api.executions._persist_or_update_execution",
            side_effect=mock_persist_always_fails,
        ),
        pytest.raises(PersistenceError) as exc_info,
    ):
        await _persist_with_retry(
            input_data=input_data,
            status_val="completed",
            max_retries=3,
            backoff_base=0.01,
        )

    assert call_count == 3
    assert "Fallo irrecuperable tras 3 reintentos" in str(exc_info.value)


@pytest.mark.asyncio
async def test_spool_emergency_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que _spool_emergency_execution escribe el volcado de la ejecución en disco."""
    monkeypatch.setattr(settings, "EMERGENCY_PERSISTENCE_DIR", str(tmp_path / "emergency"))

    payload = {"execution_id": "exec-spool-01", "status": "completed", "result": "ok"}
    spool_path = _spool_emergency_execution("exec-spool-01", payload)

    assert spool_path is not None
    assert spool_path.exists()
    assert "exec-spool-01.json" in str(spool_path)
    assert "completed" in spool_path.read_text(encoding="utf-8")


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

    with patch("app.api.executions._persist_with_retry", new_callable=AsyncMock) as mock_persist:
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
async def test_execute_graph_pipeline_fatal_persistence_failure_spools_and_raises_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifica que si la persistencia falla definitivamente tras la ejecución, se vuelca a disco y se eleva HTTP 500."""
    monkeypatch.setattr(settings, "EMERGENCY_PERSISTENCE_DIR", str(tmp_path / "emergency"))

    registry = CapabilityRegistry()
    builder = GraphBuilder(
        registry=registry,
        llm=MockChatModel(response_content="Graph execution completed"),
        security_guard=SecurityGuard(),
    )
    graph = builder.build(checkpointer=get_memory_checkpointer())

    input_data = AgentInput(
        execution_id="exec-pipe-fatal-db",
        thread_id="thread-pipe-fatal-db",
        prompt="Prueba de fallo fatal de persistencia",
    )

    with (
        patch(
            "app.api.executions._persist_with_retry",
            side_effect=PersistenceError("Simulated DB storage outage"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await execute_graph_pipeline(graph, input_data)

    assert exc_info.value.status_code == 500
    assert "Fallo crítico de persistencia tras finalización" in exc_info.value.detail

    # Verificar que se creó el fichero de emergencia en disco
    emergency_file = tmp_path / "emergency" / "exec-pipe-fatal-db.json"
    assert emergency_file.exists()


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


def test_trigger_execution_fatal_persistence_failure_returns_500(
    client_with_mock_graph: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifica que POST /executions/trigger devuelve HTTP 500 si falla la persistencia inicial (no oculta con 200)."""
    monkeypatch.setattr(settings, "EMERGENCY_PERSISTENCE_DIR", str(tmp_path / "emergency"))

    payload = {
        "execution_id": "exec-trigger-fatal-db",
        "thread_id": "thread-trigger-fatal-db",
        "prompt": "Test trigger fatal persistence",
    }

    with patch(
        "app.api.executions._persist_with_retry",
        side_effect=PersistenceError("Failed initial DB registration"),
    ):
        response = client_with_mock_graph.post("/executions/trigger", json=payload)

    assert response.status_code == 500
    data = response.json()
    assert "Fallo crítico de persistencia" in data["detail"]

    # Verificar que se generó spool de emergencia
    emergency_file = tmp_path / "emergency" / "exec-trigger-fatal-db.json"
    assert emergency_file.exists()


@pytest.mark.asyncio
async def test_resolve_hitl_execution_fatal_persistence_failure_raises_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifica que _resolve_hitl_execution eleva HTTP 500 ante fallo fatal de persistencia."""
    monkeypatch.setattr(settings, "EMERGENCY_PERSISTENCE_DIR", str(tmp_path / "emergency"))

    from app.api.executions import _resolve_hitl_execution
    from app.models.io import HITLResolutionRequest

    mock_graph = AsyncMock()
    mock_snapshot = MagicMock()
    mock_snapshot.values = {
        "request": AgentInput(
            execution_id="exec-hitl-fatal", thread_id="thread-hitl-fatal", prompt="test"
        ),
        "is_resolved": True,
    }
    mock_snapshot.next = ["human_approval"]
    mock_graph.aget_state.return_value = mock_snapshot

    mock_final_state = {
        "request": AgentInput(
            execution_id="exec-hitl-fatal", thread_id="thread-hitl-fatal", prompt="test"
        ),
        "output": AgentOutput(
            execution_id="exec-hitl-fatal",
            thread_id="thread-hitl-fatal",
            status=ExecutionStatus.COMPLETED,
            response="Aprobado y ejecutado.",
        ),
    }
    mock_graph.ainvoke.return_value = mock_final_state

    with (
        patch(
            "app.api.executions._persist_with_retry",
            side_effect=PersistenceError("Fallo en commit final HITL"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _resolve_hitl_execution(
            thread_id="thread-hitl-fatal",
            approved=True,
            payload=HITLResolutionRequest(approver="supervisor", notes="approved"),
            graph=mock_graph,
        )

    assert exc_info.value.status_code == 500
    assert "Fallo crítico de persistencia al actualizar resolución HITL" in exc_info.value.detail

    emergency_file = tmp_path / "emergency" / "exec-hitl-fatal.json"
    assert emergency_file.exists()
