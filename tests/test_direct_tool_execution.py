# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests de integración para el endpoint de ejecución directa POST /tools/{tool_name}/execute."""

import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.registry import CapabilityRegistry
from app.main import app
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.security.audit import get_security_audit_logger
from app.security.auth import (
    compute_canonical_string,
    compute_hmac_signature,
    verify_control_plane_auth,
)


@pytest.fixture
def clean_registry() -> CapabilityRegistry:
    """Provee un registry aislado para las pruebas de ejecución directa."""
    registry = CapabilityRegistry()

    def low_risk_func(message: str = "default") -> ToolResult:
        return ToolResult(success=True, output=f"Processed: {message}")

    def high_risk_func(command: str = "rm -rf") -> ToolResult:
        return ToolResult(success=True, output=f"Executed: {command}")

    registry.register_tool(
        AgentTool(
            name="echo_tool",
            description="Herramienta inocua de bajo riesgo",
            func=low_risk_func,
            risk_level=RiskLevel.LOW,
            read_only=True,
        )
    )

    registry.register_tool(
        AgentTool(
            name="critical_deploy_tool",
            description="Herramienta crítica de alto riesgo",
            func=high_risk_func,
            risk_level=RiskLevel.HIGH,
            read_only=False,
        )
    )

    app.state.registry = registry
    return registry


@pytest.mark.asyncio
async def test_direct_tool_execution_low_risk_success(clean_registry: CapabilityRegistry) -> None:
    """Verifica que una herramienta de bajo riesgo se ejecute deterministamente con 200 OK."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {"arguments": {"message": "hola desde test direct"}}
        response = await client.post("/tools/echo_tool/execute", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["tool_name"] == "echo_tool"
        assert data["success"] is True
        assert data["output"] == "Processed: hola desde test direct"
        assert "duration_ms" in data


@pytest.mark.asyncio
async def test_direct_tool_execution_not_found(clean_registry: CapabilityRegistry) -> None:
    """Verifica que invocar una herramienta no registrada devuelva HTTP 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/tools/non_existent_tool/execute", json={"arguments": {}})
        assert response.status_code == 404
        assert "no encontrada" in response.json()["detail"]


@pytest.mark.asyncio
async def test_direct_tool_execution_high_risk_requires_hitl(
    clean_registry: CapabilityRegistry,
) -> None:
    """Verifica que una herramienta de alto riesgo sea bloqueada con 409 Conflict si falta aprobación."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {"arguments": {"command": "drop database"}, "bypass_approval": False}
        response = await client.post("/tools/critical_deploy_tool/execute", json=payload)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "requiere aprobación humana" in detail["message"]
        assert detail["tool_name"] == "critical_deploy_tool"


@pytest.mark.asyncio
async def test_direct_tool_execution_high_risk_with_bypass(
    clean_registry: CapabilityRegistry,
) -> None:
    """Verifica que con bypass_approval=True se permita la ejecución de herramientas de alto riesgo."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {"arguments": {"command": "deploy production"}, "bypass_approval": True}
        response = await client.post("/tools/critical_deploy_tool/execute", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["output"] == "Executed: deploy production"


@pytest.mark.asyncio
async def test_direct_tool_execution_audit_logging(clean_registry: CapabilityRegistry) -> None:
    """Verifica que la ejecución directa quede registrada en el log de auditoría."""
    audit_logger = get_security_audit_logger()
    audit_logger.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {
            "arguments": {"message": "audited action"},
            "execution_id": "audit-test-exec-123",
        }
        response = await client.post("/tools/echo_tool/execute", json=payload)
        assert response.status_code == 200

    records = audit_logger.get_history()
    matched = [
        r
        for r in records
        if r.details.get("execution_id") == "audit-test-exec-123"
        or r.details.get("tool_name") == "echo_tool"
    ]
    assert len(matched) >= 1
    assert any(
        r.details.get("tool_name") == "echo_tool" or r.details.get("operation") == "echo_tool"
        for r in matched
    )


@pytest.mark.asyncio
async def test_direct_tool_execution_with_real_hmac_auth(
    clean_registry: CapabilityRegistry,
) -> None:
    """Verifica la invocación con firma criptográfica HMAC-SHA256 real."""
    # Restaurar la dependencia real de autenticación
    app.dependency_overrides.pop(verify_control_plane_auth, None)

    secret = "test-secret-key-123"
    settings.PERMANENT_AGENT_SECRET = secret

    timestamp = str(int(time.time()))
    body = b'{"arguments":{"message":"firmado"}}'
    canonical = compute_canonical_string(
        method="POST",
        path="/tools/echo_tool/execute",
        timestamp=timestamp,
        body_bytes=body,
    )
    sig = compute_hmac_signature(secret, canonical)

    headers = {
        "X-Agent-ID": settings.AGENT_ID,
        "X-Timestamp": timestamp,
        "X-Signature": sig,
        "Content-Type": "application/json",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/tools/echo_tool/execute", content=body, headers=headers)
        assert response.status_code == 200
        assert response.json()["success"] is True
