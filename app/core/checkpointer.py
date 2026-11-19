# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Módulo de persistencia de checkpoints para LangGraph en jg_agente.

Provee integración con PostgresSaver sobre PostgreSQL asegurando la creación y consulta
de checkpoints a través de la vista canónica core_checkpoints, habilitando pausado y
reanudación persistente (HITL, multi-worker, fallos de nodo).
"""

import asyncio
import logging
import time
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.checkpointer_allowed_classes import STATE_ALLOWED_CLASSES
from app.core.config import settings
from app.core.postgres_saver import (
    DualPostgresSaver,
)
from app.core.postgres_saver import (
    async_sanitize_for_storage as _async_sanitize_for_storage,
)
from app.core.postgres_saver import (
    sync_sanitize_for_storage as _sync_sanitize_for_storage,
)

logger = logging.getLogger("jg_agente.checkpointer")

__all__ = [
    "STATE_ALLOWED_CLASSES",
    "DualPostgresSaver",
    "ensure_core_checkpoint_views",
    "get_default_serializer",
    "close_checkpointer",
    "get_postgres_checkpointer",
    "get_memory_checkpointer",
    "get_checkpointer",
    "get_checkpointer_async",
    "_async_sanitize_for_storage",
    "_sync_sanitize_for_storage",
]


def ensure_core_checkpoint_views(conn: Any) -> None:
    """Crea o actualiza las vistas con prefijo core_ sobre las tablas nativas de checkpoints.

    Garantiza que ningún componente del sistema o consulta externa consulte tablas
    sin el prefijo 'core_'.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE OR REPLACE VIEW core_checkpoints AS
            SELECT * FROM checkpoints;

            CREATE OR REPLACE VIEW core_checkpoint_blobs AS
            SELECT * FROM checkpoint_blobs;

            CREATE OR REPLACE VIEW core_checkpoint_writes AS
            SELECT * FROM checkpoint_writes;
            """
        )


def get_default_serializer() -> JsonPlusSerializer:
    """Crea y retorna un serializador JsonPlusSerializer con las clases del Core autorizadas."""
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_ALLOWED_CLASSES)


def close_checkpointer(saver: Any) -> None:
    """Cierra el checkpointer si dispone de método close() o conexión gestionada."""
    if saver is None:
        return
    if hasattr(saver, "close") and callable(saver.close):
        try:
            saver.close()
        except Exception as exc:
            logger.warning("Error al invocar close() en checkpointer: %s", exc)


def get_postgres_checkpointer(
    connection_string: str | None = None,
    max_pool_size: int = 20,
) -> PostgresSaver:
    """Inicializa y configura un checkpointer persistente basado en PostgreSQL para LangGraph.

    Ejecuta saver.setup() e inicializa la vista core_checkpoints para compatibilidad con la
    convención de nombres estricta del Core. Soporta invocación síncrona y asíncrona (ainvoke).
    """
    uri = connection_string or settings.sync_database_url
    target_host = uri.split("@")[-1] if "@" in uri else uri
    logger.info("Inicializando PostgresSaver en '%s'", target_host)

    pool: ConnectionPool[Any] = ConnectionPool(
        conninfo=uri,
        max_size=max_pool_size,
        open=True,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    serde = get_default_serializer()
    saver = DualPostgresSaver(pool, serde=serde)

    try:
        try:
            saver.setup()
        except Exception as setup_err:
            err_str = str(setup_err).lower()
            if "already exists" in err_str or "duplicate key" in err_str:
                logger.info("Esquema de checkpoints ya inicializado previamente.")
            else:
                raise

        # Asegurar que la vista core_checkpoints exista
        with pool.connection() as conn:
            ensure_core_checkpoint_views(conn)
    except Exception:
        saver.close()
        raise

    return saver


def get_memory_checkpointer() -> MemorySaver:
    """Retorna un checkpointer en memoria para pruebas unitarias y entornos efímeros."""
    return MemorySaver(serde=get_default_serializer())


def _build_fallback_memory_saver(last_exc: Exception | None = None) -> BaseCheckpointSaver[Any]:
    """Crea una instancia de MemorySaver marcando su estado de degradación."""
    fallback_saver = get_memory_checkpointer()
    setattr(fallback_saver, "is_degraded", last_exc is not None)  # noqa: B010
    setattr(fallback_saver, "degraded_reason", str(last_exc) if last_exc else None)  # noqa: B010
    return fallback_saver


def get_checkpointer(saver_type: str | None = None) -> BaseCheckpointSaver[Any]:
    """Factory central para obtener la instancia activa de checkpointer.

    Si está configurado para PostgreSQL, intenta conectar aplicando reintentos
    con backoff exponencial. Si no logra conectar tras agotar los reintentos,
    emite una alarma crítica (CRITICAL), marca el estado de degradación en la
    instancia fallback y conmuta a MemorySaver.
    """
    kind = str(
        saver_type or getattr(settings, "CHECKPOINT_SAVER", "postgres") or "postgres"
    ).lower()

    if kind in ("postgres", "postgresql"):
        max_retries = int(getattr(settings, "CHECKPOINT_MAX_RETRIES", 3))
        base_backoff = float(getattr(settings, "CHECKPOINT_RETRY_BACKOFF_SECONDS", 0.5))
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                saver = get_postgres_checkpointer()
                setattr(saver, "is_degraded", False)  # noqa: B010
                setattr(saver, "degraded_reason", None)  # noqa: B010
                return saver
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait_seconds = base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "Intento %d/%d fallido al conectar PostgresSaver: %s. Reintentando en %.2fs...",
                        attempt,
                        max_retries,
                        exc,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                else:
                    logger.critical(
                        "FATAL: No se pudo conectar ni inicializar PostgresSaver tras %d intentos (%s). "
                        "El agente operará en modo degradado sin persistencia durable de checkpoints ni HITL.",
                        max_retries,
                        exc,
                    )

        return _build_fallback_memory_saver(last_exc)

    return _build_fallback_memory_saver()


async def get_checkpointer_async(saver_type: str | None = None) -> BaseCheckpointSaver[Any]:
    """Obtiene la instancia del checkpointer configurado usando reintentos asíncronos no bloqueantes."""
    kind = str(
        saver_type or getattr(settings, "CHECKPOINT_SAVER", "postgres") or "postgres"
    ).lower()

    if kind in ("postgres", "postgresql"):
        max_retries = int(getattr(settings, "CHECKPOINT_MAX_RETRIES", 3))
        base_backoff = float(getattr(settings, "CHECKPOINT_RETRY_BACKOFF_SECONDS", 0.5))
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                saver = get_postgres_checkpointer()
                setattr(saver, "is_degraded", False)  # noqa: B010
                setattr(saver, "degraded_reason", None)  # noqa: B010
                return saver
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait_seconds = base_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "Intento %d/%d fallido al conectar PostgresSaver: %s. Reintentando asíncronamente en %.2fs...",
                        attempt,
                        max_retries,
                        exc,
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)
                else:
                    logger.critical(
                        "FATAL: No se pudo conectar ni inicializar PostgresSaver tras %d intentos (%s). "
                        "El agente operará en modo degradado sin persistencia durable de checkpoints ni HITL.",
                        max_retries,
                        exc,
                    )

        return _build_fallback_memory_saver(last_exc)

    return _build_fallback_memory_saver()
