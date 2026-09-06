"""Tests unitarios y de integración para InfraDiscoveryEngine de jg_plugin_devops."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.registry import CapabilityRegistry
from app.models.io import AgentInput
from app.models.state import AgentExecutionStatus, AgentState
from app.nodes.observe import observe_node
from app.plugins.base import ObserverEngine
from jg_plugin_devops.discovery import InfraDiscoveryEngine
from jg_plugin_devops.models.snapshot import (
    ContainerInfo,
    CPUInfo,
    DiskPartitionInfo,
    DockerSnapshot,
    HostSnapshot,
    IncidentSeverity,
    InfraSnapshot,
    KubernetesSnapshot,
    MemoryInfo,
    OSInfo,
)


def test_engine_contract_and_metadata() -> None:
    """Valida que InfraDiscoveryEngine cumple formalmente con el contrato ObserverEngine."""
    engine = InfraDiscoveryEngine()
    assert isinstance(engine, ObserverEngine)
    assert engine.name == "infra_discovery"
    assert engine.engine_type == "observer"


@pytest.mark.asyncio
async def test_engine_lifecycle() -> None:
    """Valida los hooks de ciclo de vida del motor."""
    engine = InfraDiscoveryEngine()
    assert engine._is_started is False

    await engine.startup()
    assert engine._is_started is True

    await engine.shutdown()
    assert engine._is_started is False


@pytest.mark.asyncio
async def test_observe_telemetry_collection_and_serialization() -> None:
    """Valida que observe() retorna un diccionario serializable correspondiente a InfraSnapshot."""
    engine = InfraDiscoveryEngine()
    data = await engine.observe()

    assert isinstance(data, dict)
    assert "id" in data
    assert "timestamp" in data
    assert "host" in data
    assert "docker" in data
    assert "kubernetes" in data
    assert "incidents" in data
    assert "host_metrics" in data
    assert "topology" in data
    assert "summary" in data

    # Validar que se deserializa limpiamente en InfraSnapshot
    snapshot = InfraSnapshot.model_validate(data)
    assert snapshot.id == data["id"]
    assert snapshot.host is not None
    assert snapshot.host.hostname
    assert snapshot.topology["hostname"] == snapshot.host.hostname


@pytest.mark.asyncio
async def test_docker_fallback_when_socket_missing() -> None:
    """Verifica degradación elegante cuando el socket de Docker no existe o no responde."""
    engine = InfraDiscoveryEngine(docker_socket_path="/tmp/non_existent_docker.sock")
    with patch("jg_plugin_devops.discovery.docker", None):
        docker_snap = await engine._collect_docker_info()
        assert isinstance(docker_snap, DockerSnapshot)
        assert docker_snap.is_available is False
        assert "no encontrado" in (docker_snap.error_message or "").lower()


def test_incident_detection_heuristics() -> None:
    """Valida la detección de anomalías e incidentes ante sobrecarga de recursos o fallos."""
    engine = InfraDiscoveryEngine()

    host_overloaded = HostSnapshot(
        hostname="srv-overloaded",
        os=OSInfo(name="Linux"),
        cpu=CPUInfo(cores_logical=4, usage_percent=95.0),
        memory=MemoryInfo(
            total_bytes=16_000_000_000,
            available_bytes=800_000_000,
            used_bytes=15_200_000_000,
            percent=95.0,
        ),
        disks=[
            DiskPartitionInfo(
                mountpoint="/",
                device="/dev/sda1",
                total_bytes=100_000_000_000,
                used_bytes=94_000_000_000,
                free_bytes=6_000_000_000,
                percent=94.0,
            )
        ],
    )

    docker_snap = DockerSnapshot(
        is_available=True,
        containers=[
            ContainerInfo(
                id="c1",
                name="postgres_db",
                image="postgres:16",
                status="Exited (137) 2 minutes ago",
                state="exited",
            ),
            ContainerInfo(
                id="c2",
                name="web_api",
                image="web:v1",
                status="Up 10 minutes",
                state="running",
                health="unhealthy",
            ),
        ],
    )

    k8s_snap = KubernetesSnapshot(is_available=False)

    incidents = engine._detect_incidents(host_overloaded, docker_snap, k8s_snap)
    assert len(incidents) == 5

    titles = {inc.title for inc in incidents}
    assert any("CPU" in t for t in titles)
    assert any("Memoria" in t for t in titles)
    assert any("disco" in t for t in titles)
    assert any("unhealthy" in t for t in titles)
    assert any("detenido de forma anómala" in t for t in titles)

    severities = {inc.severity for inc in incidents}
    assert IncidentSeverity.HIGH in severities


@pytest.mark.asyncio
async def test_integration_with_observe_node_in_langgraph() -> None:
    """Valida la integración completa de InfraDiscoveryEngine con el nodo observe de LangGraph."""
    engine = InfraDiscoveryEngine()
    registry = CapabilityRegistry()
    registry.register_engine(engine)

    assert registry.get_observer() is engine

    state = AgentState(
        request=AgentInput(
            execution_id="exec-test-01",
            thread_id="thread-test-01",
            prompt="Auditar estado de la infraestructura",
        )
    )

    updates = await observe_node(state, registry=registry)

    assert updates["status"] == AgentExecutionStatus.OBSERVING
    assert "environment_snapshot" in updates
    env_snapshot = updates["environment_snapshot"]
    assert isinstance(env_snapshot, dict)
    assert "host" in env_snapshot
    assert "docker" in env_snapshot
    assert "kubernetes" in env_snapshot
    assert "incidents" in env_snapshot

    # Validar traza de auditoría
    audit_trail = updates.get("audit_trail", [])
    assert len(audit_trail) == 1
    record = audit_trail[0]
    assert record.event_type == "observe_completed"
    assert record.actor == "infra_discovery"
    assert record.details["engine"] == "infra_discovery"
    assert "host" in record.details["keys"]


@pytest.mark.asyncio
async def test_docker_sdk_parsing_mocked() -> None:
    """Verifica el mapeo de atributos del SDK de Docker cuando está activo."""
    engine = InfraDiscoveryEngine()

    mock_container = MagicMock()
    mock_container.short_id = "abc1234"
    mock_container.name = "jg_dashboard"
    mock_container.status = "Up 4 hours"
    mock_container.attrs = {
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Created": "2026-09-05T18:00:00Z",
        "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}},
    }
    mock_container.image.tags = ["jg_dashboard:latest"]
    mock_container.labels = {"env": "prod"}

    mock_client = MagicMock()
    mock_client.version.return_value = {"Version": "27.2.0"}
    mock_client.containers.list.return_value = [mock_container]
    mock_client.images.list.return_value = []
    mock_client.networks.list.return_value = []
    mock_client.volumes.list.return_value = []

    with patch("jg_plugin_devops.discovery.docker") as mock_docker:
        mock_docker.from_env.return_value = mock_client
        docker_snap = await engine._collect_docker_info()

        assert docker_snap.is_available is True
        assert docker_snap.server_version == "27.2.0"
        assert len(docker_snap.containers) == 1
        c = docker_snap.containers[0]
        assert c.name == "jg_dashboard"
        assert c.health == "healthy"
        assert len(c.ports) == 1
        assert c.ports[0].host_port == 8080
