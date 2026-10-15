# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Pruebas unitarias para el sistema de notificación webhook en ejecuciones asíncronas (AGENTE-CONC-02).

Valida que:
1. `notify_execution_completion` envía webhook autenticado con headers canónicos.
2. Soporta `callback_url` personalizada.
3. Soporta fallback a `/api/internal/...` ante 404 en `/v1/`.
4. Reintenta con backoff ante errores 5xx de servidor.
5. Es resiliente ante errores de red y excepciones inesperadas (no rompe el hilo).
6. `run_in_background` invoca garantizadamente el webhook ante éxito o ante excepciones no controladas.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.api.executions import notify_execution_completion, run_in_background
from app.models.io import AgentInput, AgentOutput, ExecutionStatus


@pytest.fixture
def sample_agent_output() -> AgentOutput:
    return AgentOutput(
        execution_id="exec-async-notify-001",
        thread_id="th-async-notify-001",
        correlation_id="cid-notify-test-123",
        status=ExecutionStatus.COMPLETED,
        response="Procesamiento completado con éxito.",
        data={"items_processed": 42},
        execution_time_ms=125.4,
        requires_approval=False,
        completed_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_agent_input() -> AgentInput:
    return AgentInput(
        execution_id="exec-async-notify-001",
        thread_id="th-async-notify-001",
        correlation_id="cid-notify-test-123",
        prompt="Tarea pesada en segundo plano",
        parameters={"async": True},
    )


@pytest.mark.asyncio
async def test_notify_execution_completion_success(sample_agent_output: AgentOutput) -> None:
    """Valida entrega exitosa de webhook al Dashboard con cabeceras de autenticación y payload tipado."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.is_success = True

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
    ) as mock_post:
        success = await notify_execution_completion(sample_agent_output)

    assert success is True
    assert mock_post.call_count == 1
    call_args, call_kwargs = mock_post.call_args
    assert "/api/v1/internal/executions/exec-async-notify-001/complete" in call_args[0]

    headers = call_kwargs["headers"]
    assert "Content-Type" in headers
    assert headers["X-Correlation-ID"] == "cid-notify-test-123"
    assert "X-Agent-ID" in headers

    payload = call_kwargs["json"]
    assert payload["execution_id"] == "exec-async-notify-001"
    assert payload["status"] == "completed"
    assert payload["execution_time_ms"] == 125.4


@pytest.mark.asyncio
async def test_notify_execution_completion_custom_callback_url(
    sample_agent_output: AgentOutput,
) -> None:
    """Valida que si se provee callback_url explícita, se despache prioritariamente a esa URL."""
    custom_url = "https://custom-webhook.internal/api/callbacks/done"
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.is_success = True

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
    ) as mock_post:
        success = await notify_execution_completion(sample_agent_output, callback_url=custom_url)

    assert success is True
    call_args, _ = mock_post.call_args
    assert call_args[0] == custom_url


@pytest.mark.asyncio
async def test_notify_execution_completion_fallback_on_404(
    sample_agent_output: AgentOutput,
) -> None:
    """Valida fallback a /api/internal/... si /api/v1/internal/... devuelve 404 Not Found."""
    resp_404 = MagicMock(spec=httpx.Response)
    resp_404.status_code = 404
    resp_404.is_success = False

    resp_200 = MagicMock(spec=httpx.Response)
    resp_200.status_code = 200
    resp_200.is_success = True

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[resp_404, resp_200]
    ) as mock_post:
        success = await notify_execution_completion(sample_agent_output)

    assert success is True
    assert mock_post.call_count == 2
    first_url = mock_post.call_args_list[0][0][0]
    second_url = mock_post.call_args_list[1][0][0]
    assert "/api/v1/internal/executions/" in first_url
    assert "/api/internal/executions/" in second_url


@pytest.mark.asyncio
async def test_notify_execution_completion_retries_on_500(
    sample_agent_output: AgentOutput,
) -> None:
    """Valida reintentos con backoff ante respuestas transitorias 500 del Control Plane."""
    resp_500 = MagicMock(spec=httpx.Response)
    resp_500.status_code = 500
    resp_500.is_success = False
    resp_500.text = "Internal Server Error"

    resp_200 = MagicMock(spec=httpx.Response)
    resp_200.status_code = 200
    resp_200.is_success = True

    with (
        patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[resp_500, resp_200]
        ) as mock_post,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        success = await notify_execution_completion(sample_agent_output)

    assert success is True
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_notify_execution_completion_network_error_resilience(
    sample_agent_output: AgentOutput,
) -> None:
    """Valida tolerancia a fallos y retorno seguro False si el destino es inalcanzable."""
    with (
        patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Network unreachable"),
        ),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        success = await notify_execution_completion(sample_agent_output)

    assert success is False


@pytest.mark.asyncio
async def test_run_in_background_success_invokes_webhook(sample_agent_input: AgentInput) -> None:
    """Valida que la finalización exitosa del pipeline invoque notify_execution_completion."""
    mock_output = AgentOutput(
        execution_id=sample_agent_input.execution_id,
        thread_id=sample_agent_input.thread_id,
        status=ExecutionStatus.COMPLETED,
        response="Pipeline background finalizado",
    )

    with (
        patch(
            "app.api.executions.execute_graph_pipeline",
            new_callable=AsyncMock,
            return_value=mock_output,
        ),
        patch(
            "app.api.executions.notify_execution_completion",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_notify,
    ):
        await run_in_background(MagicMock(), sample_agent_input)

    mock_notify.assert_called_once_with(mock_output, callback_url=None)


@pytest.mark.asyncio
async def test_run_in_background_failure_invokes_webhook_with_failed_status(
    sample_agent_input: AgentInput,
) -> None:
    """Valida que ante una excepción no capturada en el grafo, se notifique un AgentOutput de fallo."""
    with (
        patch(
            "app.api.executions.execute_graph_pipeline",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Fallo crítico en nodo de razonamiento"),
        ),
        patch(
            "app.api.executions.notify_execution_completion",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_notify,
    ):
        await run_in_background(MagicMock(), sample_agent_input)

    mock_notify.assert_called_once()
    called_output = mock_notify.call_args[0][0]
    assert isinstance(called_output, AgentOutput)
    assert called_output.status == ExecutionStatus.FAILED
    assert "Fallo crítico" in called_output.response
    assert called_output.execution_id == sample_agent_input.execution_id
