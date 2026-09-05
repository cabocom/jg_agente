"""Tests unitarios para los modelos de dominio Pydantic v2 de jg_plugin_devops."""

from datetime import UTC, datetime

from jg_plugin_devops.models.snapshot import (
    ContainerInfo,
    ContainerPortInfo,
    CPUInfo,
    DeploymentInfo,
    DiskPartitionInfo,
    DockerSnapshot,
    HostSnapshot,
    ImageInfo,
    IncidentSeverity,
    InfraIncident,
    InfraSnapshot,
    IngressInfo,
    K8sEventInfo,
    K8sServiceInfo,
    KubernetesSnapshot,
    MemoryInfo,
    NetworkInfo,
    OSInfo,
    PodInfo,
    PortInfo,
    ProcessInfo,
    ServiceInfo,
    VolumeInfo,
)


def test_host_snapshot_models() -> None:
    """Valida la creación y serialización de modelos asociados a HostSnapshot."""
    os_info = OSInfo(
        name="Linux",
        version="Ubuntu 22.04",
        kernel="5.15.0-100-generic",
        arch="x86_64",
        uptime_seconds=86400.5,
    )
    cpu_info = CPUInfo(
        cores_logical=8,
        cores_physical=4,
        usage_percent=35.2,
        load_average=[1.5, 1.2, 0.9],
    )
    mem_info = MemoryInfo(
        total_bytes=16_000_000_000,
        available_bytes=10_000_000_000,
        used_bytes=6_000_000_000,
        percent=37.5,
    )
    disk_info = DiskPartitionInfo(
        mountpoint="/",
        device="/dev/sda1",
        fstype="ext4",
        total_bytes=500_000_000_000,
        used_bytes=200_000_000_000,
        free_bytes=300_000_000_000,
        percent=40.0,
    )
    proc_info = ProcessInfo(
        pid=1234,
        name="uvicorn",
        status="running",
        cpu_percent=5.1,
        memory_percent=2.4,
        cmdline=["python", "-m", "uvicorn", "app.main:app"],
    )
    svc_info = ServiceInfo(
        name="nginx",
        state="active",
        enabled=True,
        description="Nginx HTTP Web Server",
    )
    port_info = PortInfo(
        port=80,
        protocol="tcp",
        state="LISTEN",
        process="nginx",
        pid=1234,
    )

    host = HostSnapshot(
        hostname="srv-prod-01",
        os=os_info,
        cpu=cpu_info,
        memory=mem_info,
        disks=[disk_info],
        top_processes=[proc_info],
        services=[svc_info],
        listening_ports=[port_info],
    )

    data = host.model_dump()
    assert data["hostname"] == "srv-prod-01"
    assert data["cpu"]["cores_logical"] == 8
    assert data["memory"]["percent"] == 37.5
    assert len(data["disks"]) == 1
    assert data["listening_ports"][0]["port"] == 80

    restored = HostSnapshot.model_validate(data)
    assert restored.hostname == host.hostname
    assert restored.cpu is not None and restored.cpu.usage_percent == 35.2


def test_docker_snapshot_models() -> None:
    """Valida la creación y serialización de modelos de DockerSnapshot."""
    port = ContainerPortInfo(
        container_port=8000,
        protocol="tcp",
        host_ip="0.0.0.0",
        host_port=8001,
    )
    container = ContainerInfo(
        id="c1234567890",
        name="jg_agente",
        image="jg_agente:latest",
        status="Up 3 hours",
        state="running",
        health="healthy",
        ports=[port],
        labels={"app": "agent"},
    )
    image = ImageInfo(
        id="sha256:abc123",
        tags=["python:3.11-slim"],
        size_bytes=150_000_000,
    )
    network = NetworkInfo(
        id="net123",
        name="jg_network",
        driver="bridge",
        containers=["jg_agente", "jg_agente_postgres"],
    )
    volume = VolumeInfo(
        name="pg_data",
        driver="local",
        mountpoint="/var/lib/docker/volumes/pg_data/_data",
    )

    docker_snap = DockerSnapshot(
        is_available=True,
        server_version="27.1.1",
        containers=[container],
        images=[image],
        networks=[network],
        volumes=[volume],
    )

    data = docker_snap.model_dump()
    assert data["is_available"] is True
    assert len(data["containers"]) == 1
    assert data["containers"][0]["ports"][0]["host_port"] == 8001

    restored = DockerSnapshot.model_validate(data)
    assert restored.is_available is True
    assert restored.containers[0].name == "jg_agente"


def test_kubernetes_snapshot_models() -> None:
    """Valida la creación y serialización de modelos de KubernetesSnapshot."""
    pod = PodInfo(
        name="api-gateway-7f8d9b-x9z21",
        namespace="production",
        phase="Running",
        ready=True,
        restarts=0,
        node_name="node-01",
    )
    deployment = DeploymentInfo(
        name="api-gateway",
        namespace="production",
        replicas=3,
        ready_replicas=3,
        updated_replicas=3,
        available_replicas=3,
    )
    service = K8sServiceInfo(
        name="api-gateway-svc",
        namespace="production",
        type="LoadBalancer",
        cluster_ip="10.96.0.100",
        external_ip="198.51.100.10",
        ports=[{"port": 80, "targetPort": 8080}],
    )
    ingress = IngressInfo(
        name="gateway-ingress",
        namespace="production",
        hosts=["api.example.com"],
    )
    event = K8sEventInfo(
        name="pod-pulling-image",
        namespace="production",
        reason="Pulling",
        message="Pulling image nginx:latest",
        type="Normal",
        count=1,
    )

    k8s_snap = KubernetesSnapshot(
        is_available=True,
        cluster_name="k8s-prod-cluster",
        server_version="v1.30.2",
        namespaces=["production", "monitoring"],
        pods=[pod],
        deployments=[deployment],
        services=[service],
        ingresses=[ingress],
        recent_events=[event],
    )

    dumped = k8s_snap.model_dump()
    assert dumped["is_available"] is True
    assert dumped["cluster_name"] == "k8s-prod-cluster"
    assert len(dumped["pods"]) == 1
    assert dumped["deployments"][0]["ready_replicas"] == 3


def test_infra_incident_and_severity() -> None:
    """Valida modelos de incidentes de infraestructura con enums de severidad."""
    incident = InfraIncident(
        severity=IncidentSeverity.CRITICAL,
        title="OOM Killer detectado en contenedor Redis",
        component="docker",
        description="Redis fue terminado por falta de memoria RAM.",
        details={"exit_code": 137, "container_id": "red123"},
    )

    assert incident.severity == IncidentSeverity.CRITICAL
    assert incident.severity.value == "critical"
    assert incident.resolved is False
    assert incident.id is not None
    assert isinstance(incident.created_at, datetime)

    dumped = incident.model_dump()
    assert dumped["severity"] == "critical"
    assert dumped["component"] == "docker"


def test_infra_snapshot_master_container() -> None:
    """Valida el contenedor principal InfraSnapshot y sus proyecciones de topología y métricas."""
    incident = InfraIncident(
        severity=IncidentSeverity.HIGH,
        title="High CPU Usage",
        component="host",
    )
    snap = InfraSnapshot(
        host=HostSnapshot(hostname="worker-01"),
        docker=DockerSnapshot(is_available=True),
        kubernetes=KubernetesSnapshot(is_available=False),
        incidents=[incident],
        host_metrics={"cpu_pct": 89.5, "mem_pct": 76.2},
        containers={"api": "running", "db": "running"},
        services={"nginx": "active"},
        topology={"nodes": ["worker-01"], "edges": []},
        summary="Infraestructura estable con alerta de alto uso de CPU.",
    )

    assert snap.id is not None
    assert snap.timestamp.tzinfo is UTC or snap.timestamp.tzinfo is not None
    assert snap.host is not None and snap.host.hostname == "worker-01"
    assert snap.docker is not None and snap.docker.is_available is True
    assert snap.kubernetes is not None and snap.kubernetes.is_available is False
    assert len(snap.incidents) == 1
    assert snap.containers["api"] == "running"

    json_str = snap.model_dump_json()
    assert "worker-01" in json_str
    assert "High CPU Usage" in json_str

    restored = InfraSnapshot.model_validate_json(json_str)
    assert restored.id == snap.id
    assert restored.incidents[0].title == "High CPU Usage"
