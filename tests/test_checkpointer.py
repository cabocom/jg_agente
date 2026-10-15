# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios y de integración para el Checkpointer de LangGraph y PostgresSaver."""

import uuid
from typing import Any

import psycopg
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from app.core.checkpointer import (
    close_checkpointer,
    get_checkpointer,
    get_memory_checkpointer,
    get_postgres_checkpointer,
)
from app.core.config import settings
from app.models import (
    AgentExecutionStatus,
    AgentInput,
    AgentState,
    AuditRecord,
)

# URI local del contenedor PostgreSQL iniciado en Fase 01 (puerto 5433)
LOCAL_POSTGRES_URI = "postgresql://postgres:postgres@localhost:5433/jg_agente"


def is_postgres_available(uri: str) -> bool:
    """Comprueba si el servidor PostgreSQL especificado responde a conexiones."""
    try:
        with psycopg.connect(uri, connect_timeout=2) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
            return True
    except Exception:
        return False


class TestMemoryCheckpointer:
    """Pruebas del checkpointer en memoria para entornos efímeros."""

    def test_memory_checkpointer_instance(self) -> None:
        saver = get_memory_checkpointer()
        assert isinstance(saver, MemorySaver)

    def test_get_checkpointer_fallback(self) -> None:
        saver = get_checkpointer(saver_type="memory")
        assert isinstance(saver, MemorySaver)


class TestCheckpointerLifecycleAndRetries:
    """Pruebas unitarias para el ciclo de vida, cierre de conexiones y reintentos del Checkpointer."""

    def test_dual_postgres_saver_close(self) -> None:
        """Verifica que saver.close() cierre el pool subyacente de forma idempotente."""
        from unittest.mock import MagicMock

        from app.core.checkpointer import DualPostgresSaver, get_default_serializer

        mock_pool = MagicMock()
        saver = DualPostgresSaver(conn=mock_pool, serde=get_default_serializer())

        saver.close()
        mock_pool.close.assert_called_once()

        # Idempotencia ante fallo
        mock_pool.close.side_effect = RuntimeError("Already closed")
        saver.close()  # No debe elevar excepción

    def test_close_checkpointer_helper(self) -> None:
        """Verifica que close_checkpointer invoque close() si existe y soporte None o MemorySaver."""
        from unittest.mock import MagicMock

        mock_saver = MagicMock()
        close_checkpointer(mock_saver)
        mock_saver.close.assert_called_once()

        # No falla con None ni con MemorySaver
        close_checkpointer(None)
        mem_saver = get_memory_checkpointer()
        close_checkpointer(mem_saver)

    def test_get_checkpointer_retries_and_degrades_to_memory(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verifica que get_checkpointer reintente con backoff exponencial y emita CRITICAL antes de degradar."""
        import logging

        attempts = 0
        delays: list[float] = []

        def mock_get_postgres() -> None:
            nonlocal attempts
            attempts += 1
            raise psycopg.OperationalError("Connection refused to postgres:5432")

        def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        monkeypatch.setattr("app.core.checkpointer.get_postgres_checkpointer", mock_get_postgres)
        monkeypatch.setattr("time.sleep", fake_sleep)
        monkeypatch.setattr(settings, "CHECKPOINT_MAX_RETRIES", 3)
        monkeypatch.setattr(settings, "CHECKPOINT_RETRY_BACKOFF_SECONDS", 0.1)

        with caplog.at_level(logging.WARNING):
            saver = get_checkpointer(saver_type="postgres")

        assert isinstance(saver, MemorySaver)
        assert getattr(saver, "is_degraded", False) is True
        assert "Connection refused" in str(getattr(saver, "degraded_reason", ""))
        assert attempts == 3
        assert delays == [0.1, 0.2]

        critical_logs = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert len(critical_logs) >= 1
        assert (
            "No se pudo conectar ni inicializar PostgresSaver tras 3 intentos"
            in critical_logs[0].message
        )

    def test_get_checkpointer_recovers_on_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifica recuperación exitosa si PostgreSQL responde en un intento posterior."""
        from unittest.mock import MagicMock

        attempts = 0
        mock_saver = MagicMock(spec=PostgresSaver)

        def mock_get_postgres() -> MagicMock:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise psycopg.OperationalError("Transient network glitch")
            return mock_saver

        monkeypatch.setattr("app.core.checkpointer.get_postgres_checkpointer", mock_get_postgres)
        monkeypatch.setattr("time.sleep", lambda _: None)
        monkeypatch.setattr(settings, "CHECKPOINT_MAX_RETRIES", 3)

        saver = get_checkpointer(saver_type="postgres")
        assert saver is mock_saver
        assert getattr(saver, "is_degraded", False) is False
        assert attempts == 2


class TestPostgresCheckpointerIntegration:
    """Pruebas de integración de PostgresSaver sobre la tabla y vista core_checkpoints."""

    @pytest.fixture(autouse=True)
    def check_postgres(self) -> None:
        if not is_postgres_available(LOCAL_POSTGRES_URI):
            pytest.skip("Contenedor PostgreSQL jg_agente_postgres no disponible en localhost:5433")

    def test_postgres_saver_initialization_and_views(self) -> None:
        """Verifica que PostgresSaver cree la vista core_checkpoints y responda a consultas."""
        saver = get_postgres_checkpointer(LOCAL_POSTGRES_URI)
        try:
            assert isinstance(saver, PostgresSaver)

            with psycopg.connect(LOCAL_POSTGRES_URI) as conn, conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM core_checkpoints;")
                count = cur.fetchone()
                assert count is not None
                assert isinstance(count[0], int)
        finally:
            saver.conn.close()

    def test_langgraph_flow_pause_and_resume_on_postgres(self) -> None:
        """Verifica que un grafo LangGraph persista checkpoints en core_checkpoints y reanude execution."""
        saver = get_postgres_checkpointer(LOCAL_POSTGRES_URI)
        try:
            builder = StateGraph(AgentState)

            def reason_step(state: AgentState) -> dict[str, Any]:
                return {
                    "status": AgentExecutionStatus.REASONING,
                    "messages": [AIMessage(content="Paso cognitivo de razonamiento completado.")],
                    "audit_trail": [AuditRecord(event_type="reason_completed")],
                }

            def approval_gate(state: AgentState) -> dict[str, Any]:
                return {
                    "status": AgentExecutionStatus.AWAITING_APPROVAL,
                    "messages": [AIMessage(content="Acción requiere confirmación humana (HITL).")],
                    "audit_trail": [AuditRecord(event_type="approval_requested")],
                }

            def execute_step(state: AgentState) -> dict[str, Any]:
                return {
                    "status": AgentExecutionStatus.RESOLVED,
                    "messages": [AIMessage(content="Ejecución finalizada satisfactoriamente.")],
                    "audit_trail": [AuditRecord(event_type="execution_finished")],
                    "is_resolved": True,
                }

            builder.add_node("reason", reason_step)
            builder.add_node("approval", approval_gate)
            builder.add_node("execute", execute_step)

            builder.add_edge(START, "reason")
            builder.add_edge("reason", "approval")
            builder.add_edge("approval", "execute")
            builder.add_edge("execute", END)

            # Configuramos interrupción antes de execute (simulando pausa HITL)
            graph = builder.compile(checkpointer=saver, interrupt_before=["execute"])

            thread_id = f"thread-ckpt-{uuid.uuid4().hex[:8]}"
            thread_config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

            initial_state: AgentState = {
                "request": AgentInput(
                    execution_id=f"exec-{uuid.uuid4().hex[:6]}",
                    thread_id=thread_id,
                    prompt="Iniciar tarea con checkpointing",
                ),
                "messages": [HumanMessage(content="Iniciar tarea con checkpointing")],
                "status": AgentExecutionStatus.IDLE,
                "audit_trail": [AuditRecord(event_type="pipeline_initialized")],
                "environment_snapshot": {"subsystem": "active"},
            }

            # 1. Primera ejecución: avanza por reason y approval, y se pausa antes de execute
            paused_state = graph.invoke(initial_state, config=thread_config)
            assert paused_state["status"] == AgentExecutionStatus.AWAITING_APPROVAL

            # Comprobar el siguiente nodo pendiente en el checkpointer
            state_snapshot = graph.get_state(thread_config)
            assert state_snapshot.next == ("execute",)

            # 2. Verificar físicamente la persistencia en core_checkpoints de PostgreSQL
            with psycopg.connect(LOCAL_POSTGRES_URI) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM core_checkpoints WHERE thread_id = %s;",
                    (thread_id,),
                )
                row = cur.fetchone()
                assert row is not None
                ckpt_count = row[0]
                assert ckpt_count > 0, "No se registraron checkpoints en core_checkpoints"

            # 3. Reanudación en el mismo hilo: el grafo continúa desde el checkpoint guardado
            resumed_state = graph.invoke(None, config=thread_config)
            assert resumed_state["status"] == AgentExecutionStatus.RESOLVED
            assert resumed_state["is_resolved"] is True

            # Verificar que el historial de mensajes y auditoría se haya preservado y acumulado
            messages = resumed_state["messages"]
            assert len(messages) >= 3
            assert any(
                "Ejecución finalizada" in m.content for m in messages if isinstance(m, AIMessage)
            )

            event_types = [a.event_type for a in resumed_state["audit_trail"]]
            assert "pipeline_initialized" in event_types
            assert "reason_completed" in event_types
            assert "execution_finished" in event_types
        finally:
            saver.conn.close()
