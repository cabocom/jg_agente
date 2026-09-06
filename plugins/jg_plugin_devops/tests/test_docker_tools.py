"""Tests unitarios y de integración para DockerRestartTool y su función de compensación (rollback)."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ExecutionError,
    StepExecutionRecord,
    StepStatus,
)
from app.models.tools import AgentTool, RiskLevel, ToolType
from app.nodes.rollback import rollback_node
from jg_plugin_devops.docker_tools import (
    DockerRestartArgs,
    DockerRestartTool,
    create_docker_restart_tool,
    restart_container_fn,
    rollback_restart_container_fn,
    set_docker_client,
)


@pytest.fixture(autouse=True)
def cleanup_docker_client() -> Any:
    """Asegura que el cliente inyectado se limpie después de cada test."""
    yield
    set_docker_client(None)


def test_docker_restart_args_validation() -> None:
    """Valida el esquema de argumentos DockerRestartArgs con prevención de inyecciones."""
    # Nombres válidos
    args = DockerRestartArgs(container="web_api", timeout=15)
    assert args.container == "web_api"
    assert args.timeout == 15

    # Con barra inicial (debe normalizarse)
    args_slash = DockerRestartArgs(container="/jg_agente_postgres")
    assert args_slash.container == "jg_agente_postgres"

    # Hex IDs
    args_hex = DockerRestartArgs(container="308ad84dec86")
    assert args_hex.container == "308ad84dec86"

    # Nombres inválidos con inyecciones de comandos o metacaracteres
    invalid_containers = [
        "",
        "   ",
        "web; rm -rf /",
        "web $(whoami)",
        "web | cat",
        "web`reboot`",
        "web/subpath",
        "web&echo",
    ]
    for inv in invalid_containers:
        with pytest.raises(ValidationError):
            DockerRestartArgs(container=inv)

    # Validaciones de timeout
    with pytest.raises(ValidationError):
        DockerRestartArgs(container="web", timeout=0)
    with pytest.raises(ValidationError):
        DockerRestartArgs(container="web", timeout=121)


def test_docker_restart_tool_contracts() -> None:
    """Valida los contratos formales de AgentTool para DockerRestartTool."""
    tool = create_docker_restart_tool()

    assert isinstance(tool, AgentTool)
    assert tool.name == "docker_restart"
    assert tool.risk_level == RiskLevel.HIGH
    assert tool.reversible is True
    assert tool.read_only is False
    assert tool.idempotent is False
    assert tool.tool_type == ToolType.ACTUATOR
    assert tool.args_schema is DockerRestartArgs
    assert tool.rollback_func is not None
    assert callable(tool.rollback_func)

    # Comprobación de clase directa
    tool_class = DockerRestartTool()
    assert tool_class.name == "docker_restart"
    assert tool_class.risk_level == RiskLevel.HIGH
    assert tool_class.reversible is True


def test_restart_container_fn_with_mock_client() -> None:
    """Valida el reinicio de contenedor y la captura del estado previo en rollback_context."""
    mock_container = MagicMock()
    mock_container.name = "jg_dashboard"
    mock_container.id = "c1234567890abcdef"
    mock_container.status = "running"
    mock_container.attrs = {"State": {"Status": "running"}}

    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container
    set_docker_client(mock_client)

    result = restart_container_fn(container="jg_dashboard", timeout=5)

    assert result.success is True
    assert "jg_dashboard" in str(result.output)
    mock_container.restart.assert_called_once_with(timeout=5)

    # Validar que rollback_context capturó el estado previo exacto
    assert result.rollback_context is not None
    assert result.rollback_context["container"] == "jg_dashboard"
    assert result.rollback_context["container_id"] == "c1234567890abcdef"
    assert result.rollback_context["previous_state"] == "running"
    assert result.rollback_context["action"] == "restart"


def test_restart_container_fn_not_found() -> None:
    """Valida el manejo robusto cuando el contenedor solicitado no existe."""
    from docker.errors import NotFound

    mock_client = MagicMock()
    mock_client.containers.get.side_effect = NotFound("Container not found")
    set_docker_client(mock_client)

    result = restart_container_fn(container="inexistent_container")

    assert result.success is False
    assert "No se encontró el contenedor Docker 'inexistent_container'" in (result.error or "")


def test_restart_container_fn_simulation_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valida la ejecución determinista en modo simulación sin socket Docker."""
    monkeypatch.setenv("DOCKER_SIMULATION_MODE", "true")
    set_docker_client(None)

    result = restart_container_fn(container="sim_container")

    assert result.success is True
    assert "modo simulado" in str(result.output)
    assert result.rollback_context is not None
    assert result.rollback_context["simulation"] is True
    assert result.rollback_context["previous_state"] == "running"


def test_restart_container_fn_no_daemon_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valida el reporte explícito de error cuando Docker no está disponible y no hay simulación."""
    monkeypatch.delenv("DOCKER_SIMULATION_MODE", raising=False)
    set_docker_client(None)

    # Inyectar un mock que simula no poder conectar con el socket
    class DummyNoDocker:
        pass

    with monkeypatch.context() as m:
        m.setattr("jg_plugin_devops.docker_tools.docker", None)
        result = restart_container_fn(container="any_container")
        assert result.success is False
        assert "No fue posible conectar con el daemon de Docker" in (result.error or "")


def test_rollback_restores_exited_container() -> None:
    """Verifica que el rollback detiene un contenedor que originalmente estaba 'exited'."""
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container
    set_docker_client(mock_client)

    tool = create_docker_restart_tool()

    rollback_ctx = {
        "container": "stopped_service",
        "container_id": "c987654321",
        "previous_state": "exited",
        "action": "restart",
    }

    result = tool.rollback(rollback_ctx)

    assert result.success is True
    assert result.metadata.get("target_state") == "exited"
    mock_container.stop.assert_called_once_with(timeout=10)


def test_rollback_restores_paused_container() -> None:
    """Verifica que el rollback pausa un contenedor que originalmente estaba 'paused'."""
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container
    set_docker_client(mock_client)

    tool = create_docker_restart_tool()

    rollback_ctx = {
        "container": "paused_service",
        "container_id": "c11223344",
        "previous_state": "paused",
        "action": "restart",
    }

    result = tool.rollback(rollback_ctx)

    assert result.success is True
    assert result.metadata.get("target_state") == "paused"
    mock_container.pause.assert_called_once()


def test_rollback_restores_running_container() -> None:
    """Verifica que el rollback preserva y verifica un contenedor que originalmente estaba 'running'."""
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container
    set_docker_client(mock_client)

    tool = create_docker_restart_tool()

    rollback_ctx = {
        "container": "active_service",
        "container_id": "c55667788",
        "previous_state": "running",
        "action": "restart",
    }

    result = tool.rollback(rollback_ctx)

    assert result.success is True
    assert result.metadata.get("target_state") == "running"
    # No debe detenerse ni pausarse si estaba running
    mock_container.stop.assert_not_called()
    mock_container.pause.assert_not_called()


def test_rollback_simulated_mode() -> None:
    """Verifica que el rollback en modo simulación opera de forma determinista."""
    tool = create_docker_restart_tool()

    rollback_ctx = {
        "container": "sim_service",
        "previous_state": "exited",
        "simulation": True,
    }

    result = tool.rollback(rollback_ctx)

    assert result.success is True
    assert "Compensación simulada" in str(result.output)
    assert result.metadata.get("restored_state") == "exited"


def test_rollback_invalid_context() -> None:
    """Verifica el rechazo de contextos corruptos o faltos de contenedor."""
    tool = create_docker_restart_tool()

    res_tool_empty = tool.rollback({})
    assert res_tool_empty.success is False

    res_none = rollback_restart_container_fn({})
    assert res_none.success is False
    assert "Contexto de rollback incompleto" in (res_none.error or "")

    res_type = rollback_restart_container_fn("not a dict")  # type: ignore[arg-type]
    assert res_type.success is False
    assert "Contexto de rollback inválido" in (res_type.error or "")


@pytest.mark.asyncio
async def test_rollback_node_langgraph_integration() -> None:
    """Valida la integración E2E con el nodo 'rollback_node' del grafo cognitivo."""
    mock_container = MagicMock()
    mock_container.status = "running"
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container
    set_docker_client(mock_client)

    tool = create_docker_restart_tool()
    registry = CapabilityRegistry()
    registry.register_tool(tool)

    # Estado con un paso Docker completado (que requiere compensación porque el paso 2 falló)
    state = AgentState(
        request=AgentInput(
            execution_id="exec-rollback-test",
            thread_id="session-001",
            prompt="Remediar contenedor web_api y sincronizar",
        ),
        status=AgentExecutionStatus.EXECUTING,
        execution_records=[
            StepExecutionRecord(
                step_id="step-1",
                tool_name="docker_restart",
                tool_args={"container": "web_api"},
                status=StepStatus.COMPLETED,
                output="Contenedor web_api reiniciado",
                duration_ms=150.0,
                rollback_context={
                    "container": "web_api",
                    "container_id": "c998877",
                    "previous_state": "exited",
                    "action": "restart",
                },
                timestamp=datetime.now(UTC),
            ),
            StepExecutionRecord(
                step_id="step-2",
                tool_name="failing_step",
                tool_args={},
                status=StepStatus.FAILED,
                error="Error crítico en paso posterior",
                duration_ms=50.0,
                timestamp=datetime.now(UTC),
            ),
        ],
        errors=[
            ExecutionError(
                code="FATAL_FAILURE",
                message="Fallo general en ejecución",
                component="execute",
                fatal=True,
            )
        ],
        audit_trail=[],
    )

    # Ejecución del nodo de compensación
    mutations = await rollback_node(state, registry=registry)

    # Aserciones sobre las mutaciones del estado producidas por rollback_node
    assert mutations["status"] == AgentExecutionStatus.FAILED
    assert "rollback_records" in mutations
    assert len(mutations["rollback_records"]) == 1

    rb_record = mutations["rollback_records"][0]
    assert rb_record["step_id"] == "step-1"
    assert rb_record["tool_name"] == "docker_restart"
    assert rb_record["success"] is True

    # Comprobar que mock_container fue detenido para compensar su estado previo 'exited'
    mock_container.stop.assert_called_once_with(timeout=10)

    # Comprobar que se emitió registro de auditoría inmutable
    assert "audit_trail" in mutations
    assert any(a.event_type == "rollback_completed" for a in mutations["audit_trail"])
