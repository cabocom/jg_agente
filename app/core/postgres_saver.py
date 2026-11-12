# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Implementación de DualPostgresSaver para ejecución síncrona y asíncrona."""

import asyncio
import logging
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver

logger = logging.getLogger("jg_agente.checkpointer")


async def async_sanitize_for_storage(obj: Any, depth: int = 0) -> Any:
    """Resuelve recursivamente corutinas o awaitables en estructuras de datos para checkpoints."""
    if depth > 8 or obj is None:
        return obj
    from app.core.async_compat import ensure_awaited, is_awaitable_or_coroutine

    if is_awaitable_or_coroutine(obj):
        try:
            resolved = await ensure_awaited(obj)
            return await async_sanitize_for_storage(resolved, depth + 1)
        except Exception as exc:
            logger.warning("Error resolviendo coroutine para checkpoint: %s", exc)
            return str(obj)
    if isinstance(obj, dict):
        return {k: await async_sanitize_for_storage(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [await async_sanitize_for_storage(v, depth + 1) for v in obj]
    if isinstance(obj, tuple):
        return tuple([await async_sanitize_for_storage(v, depth + 1) for v in obj])
    if hasattr(obj, "__dict__"):
        for k, v in list(vars(obj).items()):
            if is_awaitable_or_coroutine(v):
                try:
                    setattr(obj, k, await ensure_awaited(v))
                except Exception:
                    setattr(obj, k, str(v))
    return obj


def sync_sanitize_for_storage(obj: Any, depth: int = 0) -> Any:
    """Sanitiza recursivamente objetos no serializables en modo síncrono."""
    if depth > 8 or obj is None:
        return obj
    from app.core.async_compat import is_awaitable_or_coroutine

    if is_awaitable_or_coroutine(obj):
        return f"[Unresolved awaitable: {type(obj).__name__}]"
    if isinstance(obj, dict):
        return {k: sync_sanitize_for_storage(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sync_sanitize_for_storage(v, depth + 1) for v in obj]
    if isinstance(obj, tuple):
        return tuple(sync_sanitize_for_storage(v, depth + 1) for v in obj)
    if hasattr(obj, "__dict__"):
        for k, v in list(vars(obj).items()):
            if is_awaitable_or_coroutine(v):
                setattr(obj, k, f"[Unresolved awaitable: {type(v).__name__}]")
    return obj


class DualPostgresSaver(PostgresSaver):
    """PostgresSaver compatible con ejecución síncrona y asíncrona (ainvoke) de LangGraph."""

    def put(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        clean_checkpoint = sync_sanitize_for_storage(checkpoint)
        return super().put(config, clean_checkpoint, metadata, new_versions)

    def put_writes(self, config: Any, writes: Any, task_id: Any, task_path: Any = "") -> Any:
        clean_writes = sync_sanitize_for_storage(writes)
        return super().put_writes(config, clean_writes, task_id, task_path)

    async def aget_tuple(self, config: Any) -> Any:
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        clean_checkpoint = await async_sanitize_for_storage(checkpoint)
        return await asyncio.to_thread(self.put, config, clean_checkpoint, metadata, new_versions)

    async def aput_writes(self, config: Any, writes: Any, task_id: Any, task_path: Any = "") -> Any:
        clean_writes = await async_sanitize_for_storage(writes)
        return await asyncio.to_thread(self.put_writes, config, clean_writes, task_id, task_path)

    async def alist(
        self, config: Any, *, filter: Any = None, before: Any = None, limit: Any = None
    ) -> Any:
        items = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    def close(self) -> None:
        """Cierra de forma segura e idempotente el pool de conexiones subyacente."""
        pool = getattr(self, "conn", None)
        if pool is not None and hasattr(pool, "close") and callable(pool.close):
            try:
                pool.close()
                logger.info("Pool de conexiones de DualPostgresSaver cerrado exitosamente.")
            except Exception as exc:
                logger.warning("Error al cerrar pool de conexiones de DualPostgresSaver: %s", exc)
