"""Configuración global y fixtures compartidos para la suite de pruebas de jg_agente."""

from collections.abc import Generator
from typing import Any

import pytest

from app.core.config import settings
from app.main import app
from app.security.auth import verify_control_plane_auth


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla el entorno de pruebas forzando LLM_PROVIDER a 'mock' para evitar llamadas HTTP externas."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("CHECKPOINT_SAVER", "memory")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(settings, "CHECKPOINT_SAVER", "memory")


@pytest.fixture(autouse=True)
def bypass_auth_for_general_tests(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Evita requerir firmas HMAC en tests que no estén probando específicamente la autenticación."""
    if "test_api_executions_auth" not in request.node.nodeid:
        app.dependency_overrides[verify_control_plane_auth] = lambda: None
        yield
        app.dependency_overrides.pop(verify_control_plane_auth, None)
    else:
        app.dependency_overrides.pop(verify_control_plane_auth, None)
        yield


@pytest.fixture(autouse=True)
def mock_persistence_for_unit_tests(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mockea la persistencia para pruebas unitarias generales que no evalúan específicamente la base de datos."""
    if (
        "test_persistence_propagation" not in request.node.nodeid
        and "test_database_migrations" not in request.node.nodeid
    ):
        from unittest.mock import MagicMock

        from app.db.models import CoreExecution

        async def fake_persist_with_retry(*args: Any, **kwargs: Any) -> MagicMock:
            input_data = kwargs.get("input_data") or (args[0] if args else None)
            record = MagicMock(spec=CoreExecution)
            record.execution_id = getattr(input_data, "execution_id", "exec-mock")
            record.thread_id = getattr(input_data, "thread_id", "thread-mock")
            record.status = kwargs.get("status_val", "completed")
            record.error = kwargs.get("error_msg")
            record.metadata_ = {}
            record.created_at = None
            return record

        monkeypatch.setattr("app.api.executions._persist_with_retry", fake_persist_with_retry)
