"""Pruebas unitarias y de integración para el servicio de heartbeat periódico."""

import asyncio
import time
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.heartbeat import HeartbeatService, collect_system_metrics
from app.core.registry import CapabilityRegistry


def test_collect_system_metrics() -> None:
    """Valida la recolección de métricas de proceso (memoria en MB, uptime y capacidades)."""
    start_time = time.time() - 5.0
    registry = CapabilityRegistry()

    metrics = collect_system_metrics(start_time, registry)
    assert isinstance(metrics["memory_mb"], (int, float))
    assert metrics["memory_mb"] > 0
    assert metrics["uptime_seconds"] >= 5.0
    assert metrics["tools_count"] == 0
    assert metrics["plugins_count"] == 0
    assert "timestamp" in metrics
    assert "version" in metrics
    assert "cpu_percent" in metrics


@pytest.mark.asyncio
async def test_heartbeat_send_success() -> None:
    """Valida envío exitoso de heartbeat al Dashboard con código 200 y registro de métricas."""
    captured: dict[str, Any] = {}

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "status": "success",
                "message": "Heartbeat registrado exitosamente",
                "agent_id": "test-agent-uuid",
                "name": "DevOps Agent",
                "agent_status": "ACTIVE",
            },
        )

    transport = httpx.MockTransport(mock_handler)
    settings = Settings(
        DASHBOARD_URL="http://test-dashboard:8080",
        HEARTBEAT_TIMEOUT_SECONDS=2.0,
    )
    service = HeartbeatService(settings=settings, transport=transport)

    result = await service.send_heartbeat(
        agent_id="test-agent-uuid",
        permanent_secret="test_secret_123",
        status="ACTIVE",
    )

    assert result is not None
    assert result["agent_status"] == "ACTIVE"
    assert service.heartbeat_count == 1
    assert service.failed_count == 0
    assert service.last_successful_heartbeat is not None
    assert "/api/v1/agents/heartbeat" in captured["url"]
    assert "authorization" not in captured["headers"]
    assert "x-agent-secret" not in captured["headers"]
    assert "x-signature" in captured["headers"]
    assert "x-timestamp" in captured["headers"]
    assert captured["headers"]["x-agent-id"] == "test-agent-uuid"


@pytest.mark.asyncio
async def test_heartbeat_fallback_on_404() -> None:
    """Valida que si /api/v1/agents/heartbeat responde 404, reintente en /api/agents/heartbeat."""
    urls: list[str] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        urls.append(url)
        if "/api/v1/agents/heartbeat" in url:
            return httpx.Response(404, json={"error": "Not Found"})
        return httpx.Response(
            200,
            json={"status": "success", "agent_status": "ACTIVE"},
        )

    transport = httpx.MockTransport(mock_handler)
    settings = Settings(DASHBOARD_URL="http://test-dashboard:8080")
    service = HeartbeatService(settings=settings, transport=transport)

    result = await service.send_heartbeat("agent-404", "secret-404")
    assert result is not None
    assert len(urls) == 2
    assert "/api/v1/agents/heartbeat" in urls[0]
    assert "/api/agents/heartbeat" in urls[1]


@pytest.mark.asyncio
async def test_heartbeat_network_error_tolerated() -> None:
    """Valida que un fallo de red no arroje excepción ni interrumpa el proceso."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by Dashboard")

    transport = httpx.MockTransport(mock_handler)
    settings = Settings(DASHBOARD_URL="http://test-dashboard:8080")
    service = HeartbeatService(settings=settings, transport=transport)

    # No debe levantar excepción
    result = await service.send_heartbeat("agent-net", "secret-net")
    assert result is None
    assert service.failed_count == 1
    assert service.last_error is not None
    assert "Dashboard no disponible temporalmente" in service.last_error


@pytest.mark.asyncio
async def test_heartbeat_auth_error_handled() -> None:
    """Valida que credenciales rechazadas (401) se registren como error crítico sin tumbar el agente."""

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized", "message": "Secret revocado"})

    transport = httpx.MockTransport(mock_handler)
    settings = Settings(DASHBOARD_URL="http://test-dashboard:8080")
    service = HeartbeatService(settings=settings, transport=transport)

    result = await service.send_heartbeat("agent-revoked", "secret-revoked")
    assert result is None
    assert service.failed_count == 1
    assert service.last_error is not None
    assert "Credencial permanente rechazada" in service.last_error


@pytest.mark.asyncio
async def test_heartbeat_loop_start_and_stop() -> None:
    """Valida el arranque, ejecución de iteraciones y detención limpia de la tarea en background."""
    heartbeat_calls = 0

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        return httpx.Response(200, json={"status": "success", "agent_status": "ACTIVE"})

    transport = httpx.MockTransport(mock_handler)
    settings = Settings(
        DASHBOARD_URL="http://test-dashboard:8080",
        AGENT_ID="agent-loop-test",
        PERMANENT_AGENT_SECRET="secret-loop",
        HEARTBEAT_INTERVAL_SECONDS=1,  # Intervalo corto para el test
    )
    service = HeartbeatService(settings=settings, transport=transport)

    task = service.start()
    assert task is not None
    assert service.is_running is True

    # Esperar al menos un latido
    await asyncio.sleep(0.1)
    assert heartbeat_calls >= 1

    # Detener servicio
    await service.stop()
    assert service.is_running is False
    assert task.done()


def test_heartbeat_start_skips_without_secret() -> None:
    """Valida que el servicio no arranque si el agente no cuenta con credencial permanente."""
    settings = Settings(
        AGENT_ID="jg_agente_local",
        PERMANENT_AGENT_SECRET=None,
    )
    service = HeartbeatService(settings=settings)
    task = service.start()
    assert task is None
    assert service.is_running is False
