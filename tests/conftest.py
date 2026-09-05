"""Configuración global y fixtures compartidos para la suite de pruebas de jg_agente."""

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla el entorno de pruebas forzando LLM_PROVIDER a 'mock' para evitar llamadas HTTP externas."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("CHECKPOINT_SAVER", "memory")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
