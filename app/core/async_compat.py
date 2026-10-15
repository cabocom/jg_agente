# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo de compatibilidad asíncrona universal para introspección y ejecución.

Garantiza soporte uniforme entre funciones/corrutinas nativas de Python y
corrutinas compiladas bajo Cython (_cython_*.coroutine) u otros runtimes.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Coroutine
from typing import Any


def is_awaitable_or_coroutine(obj: Any) -> bool:
    """Determina si un objeto puede ser esperado con 'await'.

    Soporta corrutinas estándar de Python, Awaitables, Tasks, Future y
    corrutinas generadas por funciones compiladas con Cython (_cython_*.coroutine).
    """
    if obj is None:
        return False
    if inspect.iscoroutine(obj) or inspect.isawaitable(obj):
        return True
    if isinstance(obj, (Awaitable, Coroutine, asyncio.Future)):
        return True
    if hasattr(obj, "__await__"):
        return True

    type_name = type(obj).__name__.lower()
    return "coroutine" in type_name or "asyncgenerator" in type_name


def is_coroutine_callable(func: Any) -> bool:
    """Determina si un invocable (función, método, partial) es asíncrono.

    Soporta funciones estándar 'async def' y funciones compiladas con Cython (cyfunction).
    """
    if func is None or not callable(func):
        return False

    if inspect.iscoroutinefunction(func):
        return True

    # Soporte para functools.partial o wrappers
    unwrapped = getattr(func, "__wrapped__", None)
    if unwrapped is not None and is_coroutine_callable(unwrapped):
        return True

    func_obj = getattr(func, "func", None)
    if func_obj is not None and callable(func_obj) and is_coroutine_callable(func_obj):
        return True

    # Comprobación de código bytecode estándar
    code = getattr(func, "__code__", None)
    if code is not None and getattr(code, "co_flags", 0) & 0x80:  # CO_COROUTINE
        return True

    # Comprobación para Cython cyfunction
    type_name = type(func).__name__.lower()
    if "cyfunction" in type_name:
        if getattr(func, "_is_coroutine", False) is True:
            return True
        name = getattr(func, "__name__", "")
        if name.startswith("_async_") or "coroutine" in getattr(func, "__qualname__", "").lower():
            return True

    return False


async def ensure_awaited(val: Any, timeout: float | None = None) -> Any:
    """Espera recursiva o directamente cualquier valor awaitable si lo es.

    Si el valor no es awaitable, lo retorna inalterado.
    """
    if is_awaitable_or_coroutine(val):
        if timeout is not None:
            return await asyncio.wait_for(val, timeout=timeout)
        return await val
    return val
