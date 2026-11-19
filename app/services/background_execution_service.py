# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicio de ejecución en segundo plano para tareas asíncronas con notificación webhook."""

import logging
from datetime import UTC, datetime
from typing import Any

from app.models.io import AgentInput, AgentOutput, ExecutionStatus
from app.services.execution_notification_service import notify_execution_completion
from app.services.execution_orchestrator import execute_graph_pipeline

logger = logging.getLogger("jg_agente.services.background")


def extract_callback_url(input_data: AgentInput) -> str | None:
    """Extrae la URL de callback desde los parámetros o metadatos de AgentInput."""
    if getattr(input_data, "callback_url", None):
        return str(input_data.callback_url)
    params = input_data.parameters if isinstance(input_data.parameters, dict) else {}
    meta = input_data.metadata if isinstance(input_data.metadata, dict) else {}
    return (
        params.get("callback_url")
        or params.get("webhook_url")
        or meta.get("callback_url")
        or meta.get("webhook_url")
    )


async def run_in_background(
    graph: Any,
    input_data: AgentInput,
) -> None:
    """Ejecuta el grafo en segundo plano y despacha el webhook de notificación."""
    callback_url = extract_callback_url(input_data)
    notify_fn = notify_execution_completion
    exec_fn = execute_graph_pipeline

    agent_output: AgentOutput | None = None
    try:
        agent_output = await exec_fn(graph, input_data)
    except Exception as exc:
        logger.error(
            "Fallo en ejecución en segundo plano '%s': %s",
            input_data.execution_id,
            exc,
            exc_info=True,
        )
        agent_output = AgentOutput(
            execution_id=input_data.execution_id,
            thread_id=input_data.thread_id,
            correlation_id=input_data.correlation_id,
            status=ExecutionStatus.FAILED,
            response=f"Error durante ejecución en segundo plano: {exc}",
            data={"error": str(exc), "error_type": type(exc).__name__},
            execution_time_ms=0.0,
            completed_at=datetime.now(UTC),
            metadata=input_data.metadata,
        )
    finally:
        if agent_output is not None:
            try:
                await notify_fn(agent_output, callback_url=callback_url)
            except Exception as notify_err:
                logger.warning(
                    "Error al notificar webhook de '%s': %s",
                    input_data.execution_id,
                    notify_err,
                )
