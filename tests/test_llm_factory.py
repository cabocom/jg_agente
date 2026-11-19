# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias para la factoría get_chat_model y validación anti-fallback."""

import pytest

from app.core.config import Settings
from app.core.llm import MockChatModel, OpenAICompatibleChatModel, get_chat_model


def test_get_chat_model_unknown_provider_raises_value_error() -> None:
    """Verifica fail-loud con ValueError si el proveedor es desconocido."""
    with pytest.raises(ValueError, match="Proveedor LLM no soportado: 'proveedor_inexistente'"):
        get_chat_model(provider="proveedor_inexistente")


def test_get_chat_model_mock_in_development_allowed() -> None:
    """Verifica que MockChatModel es permitido en desarrollo."""
    cfg = Settings(ENV="development", LLM_PROVIDER="mock")
    model = get_chat_model(app_settings=cfg, provider="mock")
    assert isinstance(model, MockChatModel)


def test_get_chat_model_mock_in_production_raises_runtime_error() -> None:
    """Verifica que get_chat_model prohíbe MockChatModel en entorno de producción."""
    # Obviamos la validación de Settings instanciando con dev y mutando o pasando provider='mock'
    cfg = Settings(ENV="development", LLM_PROVIDER="groq", GROQ_API_KEY="test_key")
    cfg.ENV = "production"

    with pytest.raises(
        RuntimeError, match="MockChatModel está terminantemente prohibido en entorno de producción"
    ):
        get_chat_model(app_settings=cfg, provider="mock")

    with pytest.raises(
        RuntimeError, match="MockChatModel está terminantemente prohibido en entorno de producción"
    ):
        get_chat_model(app_settings=cfg, provider="fake")

    with pytest.raises(
        RuntimeError, match="MockChatModel está terminantemente prohibido en entorno de producción"
    ):
        get_chat_model(app_settings=cfg, provider="test")


def test_settings_forbids_mock_in_production() -> None:
    """Verifica que Settings lanza RuntimeError al arrancar con mock en producción."""
    with pytest.raises(
        RuntimeError, match="MockChatModel está terminantemente prohibido en entorno de producción"
    ):
        Settings(ENV="production", LLM_PROVIDER="mock")

    with pytest.raises(
        RuntimeError, match="MockChatModel está terminantemente prohibido en entorno de producción"
    ):
        Settings(ENV="prod", LLM_PROVIDER="fake")


def test_get_chat_model_supported_provider() -> None:
    """Verifica que proveedores soportados instancian OpenAICompatibleChatModel."""
    cfg = Settings(
        ENV="development",
        LLM_PROVIDER="openai",
        LLM_API_KEY="sk-fake-key",
    )
    model = get_chat_model(app_settings=cfg, provider="openai")
    assert isinstance(model, OpenAICompatibleChatModel)
