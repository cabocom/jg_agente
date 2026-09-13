from typing import Any

import httpx
import pytest
from langchain_core.messages import HumanMessage

from app.core.llm import OpenAICompatibleChatModel


@pytest.mark.asyncio
async def test_llm_retries_on_429_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que _agenerate reintente automáticamente tras recibir un 429 y tenga éxito."""
    attempts = 0

    async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            resp = httpx.Response(
                429,
                headers={"retry-after": "0.01", "x-ratelimit-reset-tokens": "10ms"},
                request=req,
            )
            return resp

        # Intento 2 exitoso
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        data = {
            "choices": [
                {
                    "message": {
                        "content": "Respuesta tras reintento exitoso",
                        "tool_calls": [],
                    }
                }
            ]
        }
        return httpx.Response(200, json=data, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    model = OpenAICompatibleChatModel(
        model_name="openai/gpt-oss-120b",
        api_key="fake-key",
        base_url="https://api.groq.com/openai/v1",
    )

    result = await model.ainvoke([HumanMessage(content="hola")])
    assert result.content == "Respuesta tras reintento exitoso"
    assert attempts == 2


@pytest.mark.asyncio
async def test_llm_raises_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que _agenerate lance HTTPStatusError si se agotan todos los reintentos permitidos."""
    attempts = 0

    async def mock_post_always_429(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        return httpx.Response(
            429,
            headers={"retry-after": "0.01"},
            request=req,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_always_429)

    model = OpenAICompatibleChatModel(
        model_name="openai/gpt-oss-120b",
        api_key="fake-key",
        base_url="https://api.groq.com/openai/v1",
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await model.ainvoke([HumanMessage(content="hola")])

    assert exc_info.value.response.status_code == 429
    assert attempts == 4  # Intento inicial + 3 reintentos
