"""Módulo de persistencia de checkpoints para LangGraph en jg_agente.

Provee integración con PostgresSaver sobre PostgreSQL asegurando la creación y consulta
de checkpoints a través de la vista canónica core_checkpoints, habilitando pausado y
reanudación persistente (HITL, multi-worker, fallos de nodo).
"""

import logging
import time
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import settings

logger = logging.getLogger("jg_agente.checkpointer")

# Clases autorizadas para serialización/deserialización en checkpoints de LangGraph
STATE_ALLOWED_CLASSES = [
    ("app.models", "AgentInput"),
    ("app.models.io", "AgentInput"),
    ("app.models", "AgentOutput"),
    ("app.models.io", "AgentOutput"),
    ("app.models", "UserContext"),
    ("app.models.io", "UserContext"),
    ("app.models", "ExecutionStatus"),
    ("app.models.io", "ExecutionStatus"),
    ("app.models", "AgentExecutionStatus"),
    ("app.models.state", "AgentExecutionStatus"),
    ("app.models", "ApprovalStatus"),
    ("app.models.state", "ApprovalStatus"),
    ("app.models", "StepStatus"),
    ("app.models.state", "StepStatus"),
    ("app.models", "VerificationStatus"),
    ("app.models.state", "VerificationStatus"),
    ("app.models", "RiskLevel"),
    ("app.models.tools", "RiskLevel"),
    ("app.models", "ToolType"),
    ("app.models.tools", "ToolType"),
    ("app.models", "ToolResult"),
    ("app.models.tools", "ToolResult"),
    ("app.models", "IntentModel"),
    ("app.models.state", "IntentModel"),
    ("app.models", "PlanStep"),
    ("app.models.state", "PlanStep"),
    ("app.models", "ExecutionPlan"),
    ("app.models.state", "ExecutionPlan"),
    ("app.models", "ApprovalRecord"),
    ("app.models.state", "ApprovalRecord"),
    ("app.models", "StepExecutionRecord"),
    ("app.models.state", "StepExecutionRecord"),
    ("app.models", "AuditRecord"),
    ("app.models.state", "AuditRecord"),
    ("app.models", "PolicyDecision"),
    ("app.models.state", "PolicyDecision"),
    ("app.models", "SecurityEvaluationResult"),
    ("app.models.state", "SecurityEvaluationResult"),
    ("app.models", "ExecutionError"),
    ("app.models.state", "ExecutionError"),
    ("app.models", "GoalStatus"),
    ("app.models.state", "GoalStatus"),
    ("app.models", "EvaluationRecord"),
    ("app.models.state", "EvaluationRecord"),
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


class DualPostgresSaver(PostgresSaver):
    """PostgresSaver compatible con ejecución síncrona y asíncrona (ainvoke) de LangGraph."""

    async def aget_tuple(self, config: Any) -> Any:
        import asyncio

        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        import asyncio

        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: Any, writes: Any, task_id: Any, task_path: Any = "") -> Any:
        import asyncio

        return await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(
        self, config: Any, *, filter: Any = None, before: Any = None, limit: Any = None
    ) -> Any:
        import asyncio

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


def get_checkpointer(saver_type: str | None = None) -> BaseCheckpointSaver[Any]:
    """Factory central para obtener la instancia activa de checkpointer.

    Si está configurado para PostgreSQL, intenta conectar aplicando reintentos
    con backoff exponencial. Si no logra conectar tras agotar los reintentos,
    emite una alarma crítica (CRITICAL), marca el estado de degradación en la
    instancia fallback y conmuta a MemorySaver.
    """
    raw_kind = saver_type or getattr(settings, "CHECKPOINT_SAVER", "postgres")
    kind = str(raw_kind or "postgres").lower()

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

        fallback_saver = get_memory_checkpointer()
        setattr(fallback_saver, "is_degraded", True)  # noqa: B010
        setattr(fallback_saver, "degraded_reason", str(last_exc))  # noqa: B010
        return fallback_saver

    mem_saver = get_memory_checkpointer()
    setattr(mem_saver, "is_degraded", False)  # noqa: B010
    setattr(mem_saver, "degraded_reason", None)  # noqa: B010
    return mem_saver
