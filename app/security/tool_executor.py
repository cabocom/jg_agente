# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Ejecución segura de herramientas con timeouts deterministas y manejo de asincronía."""

import asyncio
import logging
import time
from typing import Any

from app.core.async_compat import is_awaitable_or_coroutine, is_coroutine_callable
from app.models.tools import AgentTool, ToolResult

logger = logging.getLogger("jg_agente.security.tool_executor")


def _invoke_sync_func(tool: AgentTool, sanitized_args: dict[str, Any]) -> Any:
    """Invoca una función síncrona pasando argumentos posicionales o esquema."""
    try:
        return tool.func(**sanitized_args)
    except TypeError:
        if tool.args_schema:
            parsed_args = tool.args_schema(**sanitized_args)
            return tool.func(parsed_args)
        raise


async def _invoke_async_func(tool: AgentTool, sanitized_args: dict[str, Any]) -> Any:
    """Invoca una función asíncrona pasando argumentos desempaquetados o esquema."""
    try:
        return await tool.func(**sanitized_args)
    except TypeError:
        if tool.args_schema:
            parsed_args = tool.args_schema(**sanitized_args)
            return await tool.func(parsed_args)
        raise


async def invoke_tool_safely(
    tool: AgentTool,
    sanitized_args: dict[str, Any],
    timeout_sec: float = 30.0,
) -> ToolResult:
    """Ejecuta una herramienta de agente controlando límites de tiempo y excepciones."""
    start_time = time.perf_counter()

    try:
        if is_coroutine_callable(tool.func):
            raw_res = await asyncio.wait_for(
                _invoke_async_func(tool, sanitized_args), timeout=timeout_sec
            )
        else:
            raw_res = await asyncio.wait_for(
                asyncio.to_thread(_invoke_sync_func, tool, sanitized_args),
                timeout=timeout_sec,
            )
            if is_awaitable_or_coroutine(raw_res):
                raw_res = await asyncio.wait_for(raw_res, timeout=timeout_sec)

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        if isinstance(raw_res, ToolResult):
            tool_res = raw_res
            if is_awaitable_or_coroutine(tool_res.output):
                tool_res.output = await asyncio.wait_for(tool_res.output, timeout=timeout_sec)
            if tool_res.duration_ms <= 0.0:
                tool_res.duration_ms = duration_ms
            return tool_res

        return ToolResult(
            success=True,
            output=raw_res,
            duration_ms=duration_ms,
        )

    except TimeoutError:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        err_msg = (
            f"TimeoutError: La herramienta '{tool.name}' superó el tiempo límite de {timeout_sec}s."
        )
        logger.warning("[SecurityGuard] %s", err_msg)
        return ToolResult(
            success=False,
            error=err_msg,
            duration_ms=duration_ms,
            metadata={"timeout_sec": timeout_sec, "timed_out": True},
        )
    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.exception("Fallo en ejecución de tool '%s': %s", tool.name, exc)
        return ToolResult(
            success=False,
            error=f"Excepción durante la ejecución de '{tool.name}': {exc}",
            duration_ms=duration_ms,
            metadata={"exception": str(exc)},
        )
