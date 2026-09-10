"""Pruebas unitarias para el interceptor de seguridad SecurityGuard."""

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

from pydantic import BaseModel, Field

from app.models.state import PolicyDecision
from app.models.tools import AgentTool, RiskLevel, ToolResult, ToolType
from app.security.audit import SecurityAuditLogger
from app.security.guard import SecurityGuard, get_security_guard
from app.security.ssrf import SSRFValidator


class DummyArgs(BaseModel):
    query: str = Field(default="")
    target_url: str | None = Field(default=None)


def mock_tool_func(**kwargs: Any) -> ToolResult:
    return ToolResult(success=True, output=f"Executed with {kwargs}", duration_ms=10.0)


class TestSecurityGuardPermissions:
    """Pruebas de control de acceso y verificación de permisos en SecurityGuard."""

    def test_denies_when_missing_required_permissions(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="system_reboot",
            description="Reboot system",
            category="system",
            args_schema=DummyArgs,
            func=mock_tool_func,
            required_permissions=["system:admin", "host:reboot"],
            risk_level=RiskLevel.HIGH,
        )

        eval_res = guard.evaluate(
            tool=tool,
            tool_args={"query": "reboot"},
            caller_permissions=["read:metrics"],
        )

        assert eval_res.decision == PolicyDecision.DENY
        assert "Permisos insuficientes" in eval_res.reason
        assert len(audit.get_history()) == 1
        assert audit.get_history()[0].event_type == "security_decision"
        assert audit.get_history()[0].details["decision"] == "deny"

    def test_allows_when_required_permissions_satisfied(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="read_status",
            description="Read status",
            category="system",
            args_schema=DummyArgs,
            func=mock_tool_func,
            required_permissions=["metrics:read"],
            risk_level=RiskLevel.LOW,
        )

        eval_res = guard.evaluate(
            tool=tool,
            tool_args={"query": "cpu"},
            caller_permissions=["metrics:read", "other:perm"],
        )

        assert eval_res.decision == PolicyDecision.ALLOW
        assert len(audit.get_history()) == 1
        assert audit.get_history()[0].details["decision"] == "allow"


class TestSecurityGuardInjectionAndTraversal:
    """Pruebas de detección de inyecciones de comandos shell y directory traversal."""

    def test_blocks_shell_injection_metacharacters(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="service_manager",
            description="Manage services",
            category="system",
            args_schema=DummyArgs,
            func=mock_tool_func,
            risk_level=RiskLevel.LOW,
        )

        malicious_args = {"service_name": "nginx; rm -rf /"}
        eval_res = guard.evaluate(tool=tool, tool_args=malicious_args)

        assert eval_res.decision == PolicyDecision.DENY
        assert "inyección" in eval_res.reason.lower()

    def test_blocks_directory_traversal_to_system_paths(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="file_reader",
            description="Read file",
            category="filesystem",
            args_schema=DummyArgs,
            func=mock_tool_func,
            risk_level=RiskLevel.LOW,
        )

        traversal_args = {"path": "/etc/shadow"}
        eval_res = guard.evaluate(tool=tool, tool_args=traversal_args)

        assert eval_res.decision == PolicyDecision.DENY
        assert "protegida" in eval_res.reason.lower()


class TestSecurityGuardSSRF:
    """Pruebas de integración de reglas SSRF en SecurityGuard."""

    def test_blocks_ssrf_on_http_tools(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        ssrf = SSRFValidator(allowed_hosts=["api.cabocom.net"])
        guard = SecurityGuard(audit_logger=audit, ssrf_validator=ssrf)

        tool = AgentTool(
            name="weather_fetcher",
            description="Fetch weather",
            category="network",
            args_schema=DummyArgs,
            func=mock_tool_func,
            makes_http_requests=True,
            risk_level=RiskLevel.LOW,
        )

        # Intento de acceso a metadatos de AWS
        args = {"target_url": "http://169.254.169.254/latest/meta-data/"}
        eval_res = guard.evaluate(tool=tool, tool_args=args)

        assert eval_res.decision == PolicyDecision.DENY
        assert "ssrf" in eval_res.reason.lower()

    def test_allows_authorized_domain_on_http_tools(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        ssrf = SSRFValidator(allowed_hosts=["api.cabocom.net"])
        guard = SecurityGuard(audit_logger=audit, ssrf_validator=ssrf)

        tool = AgentTool(
            name="weather_fetcher",
            description="Fetch weather",
            category="network",
            args_schema=DummyArgs,
            func=mock_tool_func,
            makes_http_requests=True,
            risk_level=RiskLevel.LOW,
        )

        args = {"target_url": "https://api.cabocom.net/weather"}
        eval_res = guard.evaluate(tool=tool, tool_args=args)

        assert eval_res.decision == PolicyDecision.ALLOW


class TestSecurityGuardHITLGate:
    """Pruebas de categorización de riesgo e interrupción HITL."""

    def test_critical_and_high_risk_require_human_approval(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool_high = AgentTool(
            name="db_migration",
            description="Run migration",
            category="database",
            args_schema=DummyArgs,
            func=mock_tool_func,
            risk_level=RiskLevel.HIGH,
            reversible=False,
        )
        tool_critical = AgentTool(
            name="drop_cluster",
            description="Drop cluster",
            category="database",
            args_schema=DummyArgs,
            func=mock_tool_func,
            risk_level=RiskLevel.CRITICAL,
            reversible=False,
        )

        res_high = guard.evaluate(tool=tool_high, tool_args={})
        assert res_high.decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL

        res_crit = guard.evaluate(tool=tool_critical, tool_args={})
        assert res_crit.decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL
        assert res_crit.can_cause_data_loss is True


class TestSecurityGuardExecution:
    """Pruebas completas del interceptor execute_tool con control de timeout y concurrencia."""

    async def test_execute_tool_denied_does_not_invoke_func(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        mock_func = MagicMock()
        tool = AgentTool(
            name="rm_tool",
            description="Delete file",
            category="filesystem",
            args_schema=DummyArgs,
            func=mock_func,
            required_permissions=["admin:delete"],
        )

        res = await guard.execute_tool(
            tool=tool,
            tool_args={"path": "/etc/hosts"},
            caller_permissions=[],
        )

        assert res.success is False
        assert "DENY" in (res.error or "")
        mock_func.assert_not_called()

    async def test_execute_tool_hitl_signals_approval_needed(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        mock_func = MagicMock()
        tool = AgentTool(
            name="restart_host",
            description="Restart host",
            category="system",
            args_schema=DummyArgs,
            func=mock_func,
            risk_level=RiskLevel.HIGH,
        )

        res = await guard.execute_tool(tool=tool, tool_args={})
        assert res.success is False
        assert "REQUIRE_HUMAN_APPROVAL" in (res.error or "")
        assert res.metadata.get("requires_approval") is True
        mock_func.assert_not_called()

    async def test_execute_tool_allowed_sanitizes_and_runs(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="echo_tool",
            description="Echo query",
            category="utility",
            args_schema=DummyArgs,
            func=mock_tool_func,
            risk_level=RiskLevel.LOW,
            tool_type=ToolType.READ,
        )

        # Entrada con espacios y caracteres nulos a sanitizar
        tool_args = {"query": "  hola mundo\x00  "}
        res = await guard.execute_tool(tool=tool, tool_args=tool_args)

        assert res.success is True
        assert "hola mundo" in str(res.output)
        # Verificar que se auditó la ejecución de la herramienta
        history = audit.get_history()
        assert any(r.event_type == "tool_executed" for r in history)

    async def test_execute_tool_async_tool_success(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        async def _async_func(**kwargs: Any) -> ToolResult:
            await asyncio.sleep(0.01)
            return ToolResult(success=True, output="async_ok")

        tool = AgentTool(
            name="async_sample",
            description="Async tool",
            category="test",
            args_schema=DummyArgs,
            func=_async_func,
            risk_level=RiskLevel.LOW,
        )

        res = await guard.execute_tool(tool=tool, tool_args={"query": "test"})
        assert res.success is True
        assert res.output == "async_ok"

    async def test_execute_tool_async_tool_timeout(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        async def _slow_async_func(**kwargs: Any) -> ToolResult:
            await asyncio.sleep(0.5)
            return ToolResult(success=True, output="never_reached")

        tool = AgentTool(
            name="slow_async_tool",
            description="Slow async tool",
            category="test",
            args_schema=DummyArgs,
            func=_slow_async_func,
            risk_level=RiskLevel.LOW,
            timeout_sec=0.1,
        )

        res = await guard.execute_tool(tool=tool, tool_args={"query": "timeout"})
        assert res.success is False
        assert "TimeoutError" in (res.error or "")
        assert res.metadata.get("timed_out") is True
        assert res.metadata.get("timeout_sec") == 0.1

        # Auditoría inmutable de fallo por timeout
        history = audit.get_history()
        assert any(
            r.event_type == "tool_executed" and r.details.get("success") is False for r in history
        )

    async def test_execute_tool_sync_tool_timeout_does_not_block_worker(self) -> None:
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        def _slow_sync_func(**kwargs: Any) -> ToolResult:
            time.sleep(0.4)
            return ToolResult(success=True, output="never_reached")

        tool = AgentTool(
            name="slow_sync_tool",
            description="Slow sync tool",
            category="test",
            args_schema=DummyArgs,
            func=_slow_sync_func,
            risk_level=RiskLevel.LOW,
            timeout_sec=0.1,
        )

        start = time.perf_counter()
        res = await guard.execute_tool(tool=tool, tool_args={"query": "timeout"})
        elapsed = time.perf_counter() - start

        assert res.success is False
        assert "TimeoutError" in (res.error or "")
        assert res.metadata.get("timed_out") is True
        # El timeout debe cancelarse oportunamente (~0.1s - 0.25s) sin bloquear indefinidamente
        assert elapsed < 0.35


def test_singleton_guard_factory() -> None:
    g1 = get_security_guard()
    g2 = get_security_guard()
    assert g1 is g2
    assert isinstance(g1, SecurityGuard)
