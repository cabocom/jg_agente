"""Módulo de persistencia de checkpoints para LangGraph en jg_agente.

Provee integración con PostgresSaver sobre PostgreSQL asegurando la creación y consulta
de checkpoints a través de la vista canónica core_checkpoints, habilitando pausado y
reanudación persistente (HITL, multi-worker, fallos de nodo).
"""

import logging
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
    ("app.models", "ExecutionError"),
    ("app.models.state", "ExecutionError"),
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


def get_postgres_checkpointer(
    connection_string: str | None = None,
    max_pool_size: int = 20,
) -> PostgresSaver:
    """Inicializa y configura un checkpointer persistente basado en PostgreSQL para LangGraph.

    Ejecuta saver.setup() e inicializa la vista core_checkpoints para compatibilidad con la
    convención de nombres estricta del Core.
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
    saver = PostgresSaver(pool, serde=serde)

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

    return saver


def get_memory_checkpointer() -> MemorySaver:
    """Retorna un checkpointer en memoria para pruebas unitarias y entornos efímeros."""
    return MemorySaver(serde=get_default_serializer())


def get_checkpointer(saver_type: str | None = None) -> BaseCheckpointSaver[Any]:
    """Factory central para obtener la instancia activa de checkpointer."""
    raw_kind = saver_type or getattr(settings, "CHECKPOINT_SAVER", "postgres")
    kind = str(raw_kind or "postgres").lower()

    if kind in ("postgres", "postgresql"):
        try:
            return get_postgres_checkpointer()
        except Exception as exc:
            logger.warning(
                "No se pudo inicializar PostgresSaver (%s). Conmutando a MemorySaver.", exc
            )

    return get_memory_checkpointer()
