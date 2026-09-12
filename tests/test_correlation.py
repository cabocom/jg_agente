"""Tests unitarios y de integración para el sistema de propagación de Correlation-ID en jg_agente."""

import logging
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.correlation import (
    CorrelationIdMiddleware,
    CorrelationLogFilter,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.models.io import AgentInput
from app.models.state import PolicyDecision, SecurityEvaluationResult
from app.models.tools import RiskLevel
from app.security.audit import SecurityAuditLogger


def test_context_var_lifecycle() -> None:
    """Valida el ciclo de vida de la variable de contexto (get, set, reset)."""
    assert get_correlation_id() is None

    test_cid = "corr-test-" + str(uuid.uuid4())
    token = set_correlation_id(test_cid)
    try:
        assert get_correlation_id() == test_cid
    finally:
        reset_correlation_id(token)

    assert get_correlation_id() is None


def test_correlation_log_filter() -> None:
    """Valida que el filtro de logging inyecte el prefijo [cid: ...] cuando existe."""
    log_filter = CorrelationLogFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Mensaje de prueba",
        args=(),
        exc_info=None,
    )

    # Sin correlation_id activo
    log_filter.filter(record)
    assert getattr(record, "correlation_id", "") == ""

    # Con correlation_id activo
    test_cid = "trace-uuid-1234"
    token = set_correlation_id(test_cid)
    try:
        log_filter.filter(record)
        assert getattr(record, "correlation_id", "") == f"[{test_cid}] "
    finally:
        reset_correlation_id(token)


def test_correlation_middleware_generates_id() -> None:
    """Valida que el middleware genere un UUIDv4 cuando no se proporciona cabecera X-Correlation-ID."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    captured_cid: str | None = None

    @app.get("/test-endpoint")
    def test_endpoint() -> dict[str, str | None]:
        nonlocal captured_cid
        captured_cid = get_correlation_id()
        return {"status": "ok"}

    client = TestClient(app)
    response = client.get("/test-endpoint")

    assert response.status_code == 200
    res_cid = response.headers.get("X-Correlation-ID")
    assert res_cid is not None
    assert len(res_cid) > 10
    assert captured_cid == res_cid


def test_correlation_middleware_propagates_existing_id() -> None:
    """Valida que el middleware preserve y devuelva un X-Correlation-ID provisto por el cliente."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    captured_cid: str | None = None

    @app.get("/test-endpoint")
    def test_endpoint() -> dict[str, str | None]:
        nonlocal captured_cid
        captured_cid = get_correlation_id()
        return {"status": "ok"}

    client = TestClient(app)
    expected_cid = "dashboard-req-9988776655"
    response = client.get("/test-endpoint", headers={"X-Correlation-ID": expected_cid})

    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID") == expected_cid
    assert captured_cid == expected_cid


def test_security_audit_captures_correlation_id() -> None:
    """Valida que SecurityAuditLogger asocie automáticamente el correlation_id activo a los registros."""
    test_cid = "cid-audit-trace-55"
    token = set_correlation_id(test_cid)
    audit = SecurityAuditLogger(auto_persist=False)

    try:
        # 1. Registrar estímulo
        input_data = AgentInput(
            execution_id="exec-corr-01",
            thread_id="thread-corr-01",
            prompt="Test prompt con correlation",
        )
        stimulus_record = audit.record_stimulus(input_data)
        assert stimulus_record.correlation_id == test_cid
        assert stimulus_record.details["correlation_id"] == test_cid

        # 2. Registrar evaluación de seguridad
        evaluation = SecurityEvaluationResult(
            decision=PolicyDecision.ALLOW,
            operation="read_logs",
            target_resource="host",
            risk_level=RiskLevel.LOW,
            reason="Lectura de bajo riesgo",
        )
        eval_record = audit.record(evaluation, execution_id="exec-corr-01")
        assert eval_record.correlation_id == test_cid
        assert eval_record.details["correlation_id"] == test_cid
    finally:
        reset_correlation_id(token)
