# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios para los contratos de entrada y salida AgentInput y AgentOutput."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models import (
    AgentInput,
    AgentOutput,
    ExecutionStatus,
    UserContext,
)


class TestUserContext:
    """Pruebas del submodelo UserContext."""

    def test_user_context_default_values(self) -> None:
        ctx = UserContext()
        assert ctx.user_id is None
        assert ctx.username is None
        assert ctx.email is None
        assert ctx.role is None
        assert ctx.permissions == []
        assert ctx.metadata == {}

    def test_user_context_populated_values(self) -> None:
        ctx = UserContext(
            user_id="usr-123",
            username="jgalvez",
            email="jgalvez@example.com",
            role="admin",
            permissions=["tools:execute", "infra:restart"],
            metadata={"department": "SRE"},
        )
        assert ctx.user_id == "usr-123"
        assert ctx.role == "admin"
        assert len(ctx.permissions) == 2
        assert ctx.metadata["department"] == "SRE"

    def test_user_context_allows_extra_fields(self) -> None:
        ctx = UserContext.model_validate({"user_id": "usr-999", "custom_tenant": "tenant-alpha"})
        assert ctx.user_id == "usr-999"
        assert ctx.model_dump()["custom_tenant"] == "tenant-alpha"


class TestAgentInput:
    """Pruebas para el contrato AgentInput."""

    def test_agent_input_canonical_fields(self) -> None:
        inp = AgentInput(
            execution_id="exec-001",
            thread_id="th-001",
            prompt="Reiniciar servidor web",
            parameters={"service": "nginx"},
            metadata={"origin": "dashboard"},
        )
        assert inp.execution_id == "exec-001"
        assert inp.thread_id == "th-001"
        assert inp.prompt == "Reiniciar servidor web"
        assert inp.parameters == {"service": "nginx"}
        assert inp.metadata == {"origin": "dashboard"}
        assert inp.user_context is None
        assert isinstance(inp.created_at, datetime)
        assert inp.created_at.tzinfo is not None

    def test_agent_input_with_aliases(self) -> None:
        """Verifica compatibilidad con session_id (por thread_id) y message (por prompt)."""
        raw_payload = {
            "execution_id": "exec-002",
            "session_id": "sess-abc",
            "message": "¿Cuál es el pronóstico para mañana?",
            "user_context": {
                "user_id": "u-42",
                "role": "operator",
            },
        }
        inp = AgentInput.model_validate(raw_payload)
        assert inp.execution_id == "exec-002"
        assert inp.thread_id == "sess-abc"
        assert inp.prompt == "¿Cuál es el pronóstico para mañana?"
        assert inp.user_context is not None
        assert inp.user_context.user_id == "u-42"
        assert inp.user_context.role == "operator"

    def test_agent_input_missing_required_fields_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AgentInput.model_validate({"parameters": {}})
        errors = exc_info.value.errors()
        missing_fields = {e["loc"][0] for e in errors}
        assert "execution_id" in missing_fields
        assert "thread_id" in missing_fields
        assert "prompt" in missing_fields

    def test_agent_input_json_roundtrip(self) -> None:
        original = AgentInput(
            execution_id="exec-rt",
            thread_id="th-rt",
            prompt="Ping health",
            parameters={"timeout": 5},
            user_context=UserContext(user_id="u-rt", role="admin"),
        )
        json_str = original.model_dump_json()
        restored = AgentInput.model_validate_json(json_str)

        assert restored.execution_id == original.execution_id
        assert restored.thread_id == original.thread_id
        assert restored.prompt == original.prompt
        assert restored.parameters == original.parameters
        assert restored.user_context is not None
        assert restored.user_context.user_id == "u-rt"


class TestAgentOutput:
    """Pruebas para el contrato AgentOutput."""

    def test_agent_output_canonical_fields(self) -> None:
        out = AgentOutput(
            execution_id="exec-001",
            thread_id="th-001",
            response="Servicio reiniciado satisfactoriamente",
            data={"container_id": "c12345", "status": "running"},
            execution_time_ms=145.8,
        )
        assert out.execution_id == "exec-001"
        assert out.thread_id == "th-001"
        assert out.status == ExecutionStatus.COMPLETED
        assert out.response == "Servicio reiniciado satisfactoriamente"
        assert out.data == {"container_id": "c12345", "status": "running"}
        assert out.execution_time_ms == 145.8
        assert out.requires_approval is False
        assert out.pending_approval_id is None
        assert out.error is None
        assert isinstance(out.completed_at, datetime)

    def test_agent_output_with_alias_and_hitl(self) -> None:
        """Verifica uso del alias 'answer' y flags de Human-in-the-loop."""
        raw_payload = {
            "execution_id": "exec-hitl",
            "session_id": "sess-hitl",
            "status": "waiting_approval",
            "answer": "Se requiere autorización para reiniciar la base de datos",
            "requires_approval": True,
            "pending_approval_id": "action-appr-99",
            "execution_time_ms": 32.5,
        }
        out = AgentOutput.model_validate(raw_payload)
        assert out.thread_id == "sess-hitl"
        assert out.response == "Se requiere autorización para reiniciar la base de datos"
        assert out.status == ExecutionStatus.WAITING_APPROVAL
        assert out.requires_approval is True
        assert out.pending_approval_id == "action-appr-99"

    def test_agent_output_failed_status_with_error(self) -> None:
        out = AgentOutput(
            execution_id="exec-err",
            thread_id="th-err",
            status=ExecutionStatus.FAILED,
            response="Error interno durante la ejecución",
            error="ConnectionRefusedError: Unable to connect to host",
            execution_time_ms=500.0,
        )
        assert out.status == ExecutionStatus.FAILED
        assert out.error is not None
        assert "ConnectionRefusedError" in out.error

    def test_agent_output_negative_time_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            AgentOutput(
                execution_id="exec-inv",
                thread_id="th-inv",
                response="Respuesta",
                execution_time_ms=-10.0,
            )

    def test_agent_output_json_roundtrip(self) -> None:
        original = AgentOutput(
            execution_id="exec-out-rt",
            thread_id="th-out-rt",
            status=ExecutionStatus.COMPLETED,
            response="Todo en orden",
            data={"metric": 99.9},
            execution_time_ms=88.4,
            completed_at=datetime.now(UTC),
        )
        json_str = original.model_dump_json()
        restored = AgentOutput.model_validate_json(json_str)

        assert restored.execution_id == original.execution_id
        assert restored.thread_id == original.thread_id
        assert restored.status == ExecutionStatus.COMPLETED
        assert restored.response == original.response
        assert restored.data == {"metric": 99.9}
        assert restored.execution_time_ms == 88.4
