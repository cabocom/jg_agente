# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Proveedor y factoría de modelos de lenguaje (LLM) para jg_agente.

Proporciona abstracciones configurables y desacopladas para interactuar con modelos
de lenguaje mediante LangChain BaseChatModel, incluyendo un proveedor Mock determinista
para testing y ejecución local, y un cliente compatible con OpenAI/vLLM/Ollama vía HTTP.
"""

import asyncio
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import Settings, settings
from app.core.llm_mock import MockChatModel
from app.core.llm_openai import OpenAICompatibleChatModel
from app.core.llm_ratelimit import (
    RATE_LIMIT_JITTER_MAX_SECONDS,
    RATE_LIMIT_JITTER_MIN_SECONDS,
    compute_rate_limit_wait,
    parse_duration_seconds,
)

logger = logging.getLogger("jg_agente.core.llm")


def _resolve_base_url(chosen_provider: str, configured_url: str | None) -> str:
    """Determina la URL base para el proveedor compatible con OpenAI."""
    if configured_url:
        return configured_url
    if chosen_provider == "ollama":
        return "http://localhost:11434/v1"
    if chosen_provider == "groq":
        return "https://api.groq.com/openai/v1"
    if chosen_provider == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta/openai/"
    return "https://api.openai.com/v1"


def get_chat_model(
    app_settings: Settings | None = None,
    provider: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Factoría centralizada para instanciar el modelo de chat configurado."""
    cfg = app_settings or settings
    chosen_provider = (provider or cfg.LLM_PROVIDER).lower().strip()
    chosen_model = model or cfg.LLM_MODEL

    if chosen_provider in ("mock", "fake", "test"):
        return MockChatModel(**kwargs)

    if chosen_provider in ("openai", "custom", "ollama", "vllm", "groq", "gemini"):
        base_url = _resolve_base_url(chosen_provider, cfg.LLM_BASE_URL)
        return OpenAICompatibleChatModel(
            model_name=chosen_model,
            api_key=cfg.LLM_API_KEY,
            base_url=base_url,
            temperature=cfg.LLM_TEMPERATURE,
            max_tokens=cfg.LLM_MAX_TOKENS,
            **kwargs,
        )

    logger.warning(
        "Proveedor LLM desconocido '%s'. Se usará MockChatModel por defecto.",
        chosen_provider,
    )
    return MockChatModel(**kwargs)


__all__ = [
    "MockChatModel",
    "OpenAICompatibleChatModel",
    "RATE_LIMIT_JITTER_MAX_SECONDS",
    "RATE_LIMIT_JITTER_MIN_SECONDS",
    "asyncio",
    "compute_rate_limit_wait",
    "get_chat_model",
    "parse_duration_seconds",
]
