"""Configuración global y fixtures compartidos para la suite de pruebas de jg_agente."""

from collections.abc import Generator

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
