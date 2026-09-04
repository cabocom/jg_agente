"""Pruebas unitarias y de integración para SecurityAuditLogger."""

import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import CoreAuditRecord, CoreExecution
from app.models.io import AgentInput, UserContext
from app.models.state import (
    AgentExecutionStatus,
    ApprovalRecord,
    ApprovalStatus,
    PolicyDecision,
    SecurityEvaluationResult,
)
from app.models.tools import RiskLevel, ToolResult
from app.security.audit import SecurityAuditLogger, get_security_audit_logger

LOCAL_POSTGRES_URI = "postgresql://postgres:postgres@localhost:5433/jg_agente"
LOCAL_POSTGRES_ASYNC_URI = "postgresql+asyncpg://postgres:postgres@localhost:5433/jg_agente"


def is_postgres_available(uri: str) -> bool:
    """Verifica disponibilidad del contenedor PostgreSQL."""
    try:
        with psycopg.connect(uri, connect_timeout=2) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
            return True
    except Exception:
        return False


class TestSecurityAuditLoggerUnit:
    """Pruebas en memoria y sin dependencias de infraestructura para SecurityAuditLogger."""

    def test_singleton_factory(self) -> None:
        logger1 = get_security_audit_logger()
        logger2 = get_security_audit_logger()
        assert logger1 is logger2
        assert isinstance(logger1, SecurityAuditLogger)

    def test_record_security_evaluation(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        evaluation = SecurityEvaluationResult(
            decision=PolicyDecision.REQUIRE_HUMAN_APPROVAL,
            operation="reboot_host",
            target_resource="node-prod-01",
            risk_level=RiskLevel.HIGH,
            reason="Reinicio de nodo de cómputo en producción",
            required_permissions=["system:reboot"],
            is_reversible=False,
            can_cause_data_loss=True,
        )

        record = audit.record(evaluation, execution_id="exec-test-01")
        assert record.event_type == "security_decision"
        assert record.actor == "security_guard"
        assert record.details["decision"] == "require_human_approval"
        assert record.details["operation"] == "reboot_host"
        assert record.details["risk_level"] == "high"
        assert record.details["result"] == "require_human_approval"
        assert record.details["execution_id"] == "exec-test-01"
        assert len(audit.get_history()) == 1

    def test_record_stimulus(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        user_ctx = UserContext(user_id="usr_admin", role="admin")
        inp = AgentInput(
            execution_id="exec-stim-01",
            thread_id="th-stim-01",
            prompt="Verificar estado de pods",
            user_context=user_ctx,
        )

        record = audit.record_stimulus(inp)
        assert record.event_type == "stimulus_received"
        assert record.actor == "usr_admin"
        assert record.details["execution_id"] == "exec-stim-01"
        assert record.details["prompt"] == "Verificar estado de pods"
        assert record.details["result"] == "received"
        assert record.details["risk_level"] == "low"
        assert isinstance(record.timestamp, datetime)

    def test_record_tool_execution(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        result = ToolResult(
            success=True,
            output="Container restarted successfully",
            duration_ms=450.5,
            rollback_context={"previous_state": "running"},
        )

        record = audit.record_tool_execution(
            tool_name="docker_restart",
            tool_args={"container_name": "web"},
            result=result,
            risk_level=RiskLevel.MEDIUM,
            execution_id="exec-tool-01",
            thread_id="th-tool-01",
        )

        assert record.event_type == "tool_executed"
        assert record.actor == "tool_executor"
        assert record.details["tool_name"] == "docker_restart"
        assert record.details["success"] is True
        assert record.details["result"] == "success"
        assert record.details["risk_level"] == "medium"
        assert record.details["has_rollback"] is True

    def test_record_state_transition(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        record = audit.record_state_transition(
            old_status=AgentExecutionStatus.PLANNING,
            new_status=AgentExecutionStatus.AWAITING_APPROVAL,
            execution_id="exec-trans-01",
            reason="High-risk tool requires human approval",
        )

        assert record.event_type == "state_transition"
        assert record.actor == "orchestrator"
        assert record.details["old_status"] == "planning"
        assert record.details["new_status"] == "awaiting_approval"
        assert record.details["result"] == "transitioned"

    def test_record_approval(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        approval = ApprovalRecord(
            status=ApprovalStatus.APPROVED,
            approver="alice@cabocom.net",
            notes="Autorizado para ventana de mantenimiento",
            decided_at=datetime.now(UTC),
        )

        record = audit.record_approval(
            approval, execution_id="exec-appr-01", thread_id="th-appr-01"
        )
        assert record.event_type == "approval_decided"
        assert record.actor == "alice@cabocom.net"
        assert record.details["status"] == "approved"
        assert record.details["result"] == "approved"

    def test_clear_and_get_history(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        audit.record_event("evt1", {"k": 1})
        audit.record_event("evt2", {"k": 2})
        assert len(audit.get_history()) == 2
        audit.clear()
        assert len(audit.get_history()) == 0


@pytest.mark.asyncio
class TestSecurityAuditLoggerIntegration:
    """Pruebas de persistencia asíncrona no bloqueante sobre la tabla core_audit_records."""

    @pytest.fixture(autouse=True)
    def check_postgres(self) -> None:
        if not is_postgres_available(LOCAL_POSTGRES_URI):
            pytest.skip("PostgreSQL no disponible en localhost:5433")

    @pytest.fixture
    def test_session_factory(self) -> async_sessionmaker[Any]:
        engine = create_async_engine(LOCAL_POSTGRES_ASYNC_URI)
        return async_sessionmaker(engine, expire_on_commit=False)

    async def test_async_non_blocking_persistence_with_execution(
        self, test_session_factory: async_sessionmaker[Any]
    ) -> None:
        """Verifica que los eventos se persistan en core_audit_records vinculados a core_executions."""
        exec_id = f"exec-audit-{uuid.uuid4().hex[:8]}"
        thread_id = f"th-audit-{uuid.uuid4().hex[:8]}"

        # 1. Crear ejecución en core_executions
        async with test_session_factory() as session:
            exec_row = CoreExecution(
                execution_id=exec_id,
                thread_id=thread_id,
                prompt="Auditar pipeline de seguridad",
                status="in_progress",
            )
            session.add(exec_row)
            await session.commit()

        # 2. Registrar eventos a través del SecurityAuditLogger
        audit = SecurityAuditLogger(session_factory=test_session_factory, auto_persist=True)

        # Estímulo
        inp = AgentInput(
            execution_id=exec_id,
            thread_id=thread_id,
            prompt="Auditar pipeline de seguridad",
        )
        audit.record_stimulus(inp)

        # Decisión de seguridad
        eval_res = SecurityEvaluationResult(
            decision=PolicyDecision.ALLOW,
            operation="read_metrics",
            risk_level=RiskLevel.LOW,
            reason="Lectura sin mutación",
        )
        audit.record(eval_res, execution_id=exec_id)

        # Ejecución de tool
        tool_res = ToolResult(success=True, output="100 CPU", duration_ms=12.0)
        audit.record_tool_execution(
            tool_name="read_metrics",
            tool_args={"target": "cpu"},
            result=tool_res,
            risk_level=RiskLevel.LOW,
            execution_id=exec_id,
            thread_id=thread_id,
        )

        # Transición de estado
        audit.record_state_transition(
            old_status=AgentExecutionStatus.IDLE,
            new_status=AgentExecutionStatus.RESOLVED,
            execution_id=exec_id,
            thread_id=thread_id,
        )

        # 3. Flushear tareas en segundo plano
        await audit.flush()

        # 4. Verificar en base de datos PostgreSQL
        async with test_session_factory() as session:
            stmt = (
                select(CoreAuditRecord)
                .where(CoreAuditRecord.execution_id == exec_id)
                .order_by(CoreAuditRecord.id.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            assert len(rows) == 4

            event_types = [r.event_type for r in rows]
            assert set(event_types) == {
                "stimulus_received",
                "security_decision",
                "tool_executed",
                "state_transition",
            }

            # Verificar que todos tienen timestamp, actor y detalles válidos
            for r in rows:
                assert r.timestamp is not None
                assert r.actor is not None
                assert "result" in r.details
                assert "risk_level" in r.details

    async def test_persistence_unlinked_execution_fallback(
        self, test_session_factory: async_sessionmaker[Any]
    ) -> None:
        """Verifica que si se pasa un execution_id inexistente, no falla y persiste sin FK."""
        ghost_exec_id = f"ghost-exec-{uuid.uuid4().hex[:8]}"
        audit = SecurityAuditLogger(session_factory=test_session_factory, auto_persist=True)

        eval_res = SecurityEvaluationResult(
            decision=PolicyDecision.DENY,
            operation="rm_rf",
            risk_level=RiskLevel.CRITICAL,
            reason="Comando destructivo denegado",
        )
        audit.record(eval_res, execution_id=ghost_exec_id)

        await audit.flush()

        async with test_session_factory() as session:
            stmt = (
                select(CoreAuditRecord)
                .where(CoreAuditRecord.event_type == "security_decision")
                .order_by(CoreAuditRecord.id.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one()
            assert row is not None
            assert row.details["decision"] == "deny"
            assert row.details["risk_level"] == "critical"
            # Verificar que la referencia se preservó en los detalles a pesar del fallback
            assert (
                row.details.get("unlinked_execution_id") == ghost_exec_id
                or row.details.get("execution_id") == ghost_exec_id
            )
