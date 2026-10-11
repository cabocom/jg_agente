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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2", 2.0),
        ("0.5", 0.5),
        ("250ms", 0.25),
        ("2s", 2.0),
        ("1m30s", 90.0),
        ("1h2m3.5s", 3723.5),
        ("6m0s", 360.0),
        ("  1M30S ", 90.0),
    ],
)
def test_parse_duration_seconds_valid_formats(raw: str, expected: float) -> None:
    from app.core.llm import parse_duration_seconds

    assert parse_duration_seconds(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "abc", "1x", "m30s", "1m30"])
def test_parse_duration_seconds_invalid_returns_none(raw: str | None) -> None:
    from app.core.llm import parse_duration_seconds

    assert parse_duration_seconds(raw) is None


def test_compute_rate_limit_wait_adds_jitter_and_prioritizes_headers() -> None:
    from app.core.llm import compute_rate_limit_wait

    fixed_jitter = lambda low, high: (low + high) / 2  # noqa: E731
    # Retry-After tiene prioridad sobre reset-tokens
    assert compute_rate_limit_wait(
        {"retry-after": "1m30s", "x-ratelimit-reset-tokens": "2s"}, 0, fixed_jitter
    ) == pytest.approx(90.3)
    # Solo reset-tokens en ms (con suelo de 0.5 s)
    assert compute_rate_limit_wait(
        {"x-ratelimit-reset-tokens": "100ms"}, 0, fixed_jitter
    ) == pytest.approx(0.8)
    # Sin cabeceras: backoff lineal 2.5 * (attempt + 1)
    assert compute_rate_limit_wait({}, 1, fixed_jitter) == pytest.approx(5.3)


def test_compute_rate_limit_wait_jitter_within_bounds() -> None:
    from app.core.llm import compute_rate_limit_wait

    waits = {compute_rate_limit_wait({"retry-after": "2"}, 0) for _ in range(50)}
    assert all(2.1 <= w <= 2.5 for w in waits)
    assert len(waits) > 1  # no determinista


@pytest.mark.asyncio
async def test_llm_429_sleep_uses_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """El retardo realmente aplicado en _agenerate incluye el jitter (1.0 s + [0.1, 0.5])."""
    sleeps: list[float] = []
    attempts = 0

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def mock_post(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "1s"}, request=req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr("app.core.llm.asyncio.sleep", fake_sleep)

    model = OpenAICompatibleChatModel(
        model_name="m", api_key="k", base_url="https://api.groq.com/openai/v1"
    )
    result = await model.ainvoke([HumanMessage(content="hola")])
    assert result.content == "ok"
    assert len(sleeps) == 1
    assert 1.1 <= sleeps[0] <= 1.5
