"""Motor de observación y descubrimiento de infraestructura para jg_plugin_devops.

Recolecta telemetría del host, contenedores Docker y recursos Kubernetes,
generando un InfraSnapshot serializable que se deposita en environment_snapshot
durante la ejecución del nodo 'observe' de LangGraph.
"""

import logging
import os
import platform
import shutil
import socket
import time
from pathlib import Path
from typing import Any

from app.models.state import AgentState
from app.plugins.base import ObserverEngine
from jg_plugin_devops.models.snapshot import (
    ContainerInfo,
    ContainerPortInfo,
    CPUInfo,
    DiskPartitionInfo,
    DockerSnapshot,
    HostSnapshot,
    ImageInfo,
    IncidentSeverity,
    InfraIncident,
    InfraSnapshot,
    KubernetesSnapshot,
    MemoryInfo,
    NetworkInfo,
    OSInfo,
    PortInfo,
    ProcessInfo,
    ServiceInfo,
    VolumeInfo,
)

logger = logging.getLogger("jg_plugin_devops.discovery")

# Detección condicional de librerías externas opcionales
psutil: Any
try:
    import psutil
except ImportError:
    psutil = None

docker: Any
try:
    import docker
except ImportError:
    docker = None


class InfraDiscoveryEngine(ObserverEngine):
    """Motor de observación de infraestructura SRE.

    Implementa el contrato ObserverEngine para integrarse de forma desacoplada
    en el nodo 'observe' del grafo de ejecución de jg_agente.
    """

    def __init__(self, docker_socket_path: str = "/var/run/docker.sock") -> None:
        self._docker_socket_path = docker_socket_path
        self._is_started: bool = False

    @property
    def name(self) -> str:
        """Nombre identificador único del motor."""
        return "infra_discovery"

    async def startup(self) -> None:
        """Inicialización del motor durante el boot del plugin."""
        logger.info("Iniciando InfraDiscoveryEngine...")
        self._is_started = True

    async def shutdown(self) -> None:
        """Liberación de recursos durante el apagado del plugin."""
        logger.info("Deteniendo InfraDiscoveryEngine...")
        self._is_started = False

    async def observe(self, state: AgentState | None = None) -> dict[str, Any]:
        """Recolecta la fotografía completa de la infraestructura y retorna un dict JSON-serializable.

        Este método es invocado automáticamente por el nodo 'observe' de LangGraph.
        """
        start_time = time.perf_counter()
        logger.debug("Iniciando ciclo de observación de infraestructura...")

        # 1. Recolección de subsistemas
        host = self._collect_host_info()
        docker_snap = await self._collect_docker_info()
        k8s_snap = self._collect_k8s_info()

        # 2. Detección automática de incidentes / anomalías
        incidents = self._detect_incidents(host, docker_snap, k8s_snap)

        # 3. Proyecciones rápidas para razonamiento y planificación
        host_metrics: dict[str, Any] = {}
        if host.cpu:
            host_metrics["cpu_usage_pct"] = host.cpu.usage_percent
            host_metrics["cpu_cores"] = host.cpu.cores_logical
            if host.cpu.load_average:
                host_metrics["load_average"] = host.cpu.load_average
        if host.memory:
            host_metrics["memory_usage_pct"] = host.memory.percent
            host_metrics["memory_total_gb"] = round(host.memory.total_bytes / (1024**3), 2)
            host_metrics["memory_available_gb"] = round(host.memory.available_bytes / (1024**3), 2)
        if host.disks:
            primary_disk = host.disks[0]
            host_metrics["disk_mount"] = primary_disk.mountpoint
            host_metrics["disk_usage_pct"] = primary_disk.percent
            host_metrics["disk_free_gb"] = round(primary_disk.free_bytes / (1024**3), 2)

        containers_map: dict[str, str] = {c.name: c.status for c in docker_snap.containers}
        services_map: dict[str, str] = {s.name: s.state for s in host.services}

        topology: dict[str, Any] = {
            "hostname": host.hostname,
            "os": host.os.name if host.os else "unknown",
            "containers_count": len(docker_snap.containers),
            "images_count": len(docker_snap.images),
            "docker_available": docker_snap.is_available,
            "k8s_available": k8s_snap.is_available,
            "incidents_count": len(incidents),
        }

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        summary = (
            f"Captura completada en {duration_ms}ms: Host '{host.hostname}' "
            f"(CPU: {host.cpu.usage_percent if host.cpu else 'N/A'}%, "
            f"RAM: {host.memory.percent if host.memory else 'N/A'}%), "
            f"Docker: {'Activo (' + str(len(docker_snap.containers)) + ' contenedores)' if docker_snap.is_available else 'No disponible'}, "
            f"Incidentes detectados: {len(incidents)}."
        )

        snapshot = InfraSnapshot(
            host=host,
            docker=docker_snap,
            kubernetes=k8s_snap,
            incidents=incidents,
            host_metrics=host_metrics,
            containers=containers_map,
            services=services_map,
            topology=topology,
            metadata={"collector": self.name, "duration_ms": duration_ms},
            summary=summary,
        )

        logger.debug("Observación de infraestructura finalizada exitosamente: %s", summary)
        return snapshot.model_dump(mode="json")

    # ========================================================================
    # Métodos de Recolección Específicos
    # ========================================================================

    def _collect_host_info(self) -> HostSnapshot:
        """Recolecta información y métricas del host con soporte dual (psutil / stdlib)."""
        hostname = socket.gethostname()

        # Uptime
        uptime_seconds: float | None = None
        if psutil is not None:
            try:
                boot_time = psutil.boot_time()
                uptime_seconds = round(time.time() - boot_time, 2)
            except Exception:
                pass
        if uptime_seconds is None and Path("/proc/uptime").exists():
            try:
                content = Path("/proc/uptime").read_text().split()
                uptime_seconds = float(content[0])
            except Exception:
                pass

        os_info = OSInfo(
            name=platform.system(),
            version=platform.release(),
            kernel=platform.version(),
            arch=platform.machine(),
            uptime_seconds=uptime_seconds,
        )

        # CPU
        cores_logical = os.cpu_count() or 1
        cores_physical: int | None = None
        cpu_usage_pct = 0.0
        load_avg: list[float] = []

        try:
            if hasattr(os, "getloadavg"):
                load_avg = [round(x, 2) for x in os.getloadavg()]
        except Exception:
            pass

        if psutil is not None:
            try:
                cores_physical = psutil.cpu_count(logical=False)
                cpu_usage_pct = float(psutil.cpu_percent(interval=None))
            except Exception:
                pass
        elif load_avg and cores_logical > 0:
            # Estimación basada en load average si psutil no está disponible
            cpu_usage_pct = min(round((load_avg[0] / cores_logical) * 100.0, 1), 100.0)

        cpu_info = CPUInfo(
            cores_logical=cores_logical,
            cores_physical=cores_physical,
            usage_percent=cpu_usage_pct,
            load_average=load_avg,
        )

        # Memoria
        total_bytes = 0
        available_bytes = 0
        used_bytes = 0
        mem_pct = 0.0

        if psutil is not None:
            try:
                vmem = psutil.virtual_memory()
                total_bytes = int(vmem.total)
                available_bytes = int(vmem.available)
                used_bytes = int(vmem.used)
                mem_pct = float(vmem.percent)
            except Exception:
                pass
        elif Path("/proc/meminfo").exists():
            try:
                lines = Path("/proc/meminfo").read_text().splitlines()
                mem_data: dict[str, int] = {}
                for line in lines:
                    parts = line.split(":")
                    if len(parts) == 2:
                        val_str = parts[1].strip().split()[0]
                        mem_data[parts[0].strip()] = int(val_str) * 1024  # kB a bytes
                total_bytes = mem_data.get("MemTotal", 0)
                available_bytes = mem_data.get("MemAvailable", mem_data.get("MemFree", 0))
                used_bytes = max(total_bytes - available_bytes, 0)
                if total_bytes > 0:
                    mem_pct = round((used_bytes / total_bytes) * 100.0, 1)
            except Exception:
                pass

        memory_info = MemoryInfo(
            total_bytes=total_bytes,
            available_bytes=available_bytes,
            used_bytes=used_bytes,
            percent=mem_pct,
        )

        # Discos
        disks: list[DiskPartitionInfo] = []
        try:
            root_usage = shutil.disk_usage("/")
            root_pct = (
                round((root_usage.used / root_usage.total) * 100.0, 1)
                if root_usage.total > 0
                else 0.0
            )
            disks.append(
                DiskPartitionInfo(
                    mountpoint="/",
                    device="rootfs",
                    fstype="auto",
                    total_bytes=root_usage.total,
                    used_bytes=root_usage.used,
                    free_bytes=root_usage.free,
                    percent=root_pct,
                )
            )
        except Exception as exc:
            logger.debug("No se pudo obtener el uso de disco de '/': %s", exc)

        # Procesos (si psutil está disponible)
        top_processes: list[ProcessInfo] = []
        if psutil is not None:
            try:
                for proc in sorted(
                    psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_percent"]),
                    key=lambda p: p.info.get("cpu_percent") or 0.0,
                    reverse=True,
                )[:5]:
                    pinfo = proc.info
                    top_processes.append(
                        ProcessInfo(
                            pid=pinfo.get("pid") or 0,
                            name=pinfo.get("name") or "unknown",
                            status=str(pinfo.get("status") or "running"),
                            cpu_percent=float(pinfo.get("cpu_percent") or 0.0),
                            memory_percent=float(pinfo.get("memory_percent") or 0.0),
                        )
                    )
            except Exception:
                pass

        # Puertos básicos
        listening_ports: list[PortInfo] = []

        # Servicios clave
        services: list[ServiceInfo] = []

        return HostSnapshot(
            hostname=hostname,
            os=os_info,
            cpu=cpu_info,
            memory=memory_info,
            disks=disks,
            top_processes=top_processes,
            services=services,
            listening_ports=listening_ports,
        )

    async def _collect_docker_info(self) -> DockerSnapshot:
        """Recolecta información de contenedores Docker si el socket está disponible."""
        # 1. Verificar si el SDK de Docker puede conectarse
        if docker is not None:
            try:
                client = docker.from_env(timeout=2)
                version_info = client.version()
                server_ver = version_info.get("Version", "unknown")

                containers_list: list[ContainerInfo] = []
                for c in client.containers.list(all=True):
                    ports: list[ContainerPortInfo] = []
                    port_mappings = c.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
                    for c_port_str, host_bindings in port_mappings.items():
                        parts = c_port_str.split("/")
                        p_num = int(parts[0]) if parts[0].isdigit() else 0
                        proto = parts[1] if len(parts) > 1 else "tcp"
                        if host_bindings:
                            for b in host_bindings:
                                h_port = (
                                    int(b.get("HostPort", 0))
                                    if b.get("HostPort", "").isdigit()
                                    else None
                                )
                                ports.append(
                                    ContainerPortInfo(
                                        container_port=p_num,
                                        protocol=proto,
                                        host_ip=b.get("HostIp"),
                                        host_port=h_port,
                                    )
                                )
                        else:
                            ports.append(
                                ContainerPortInfo(
                                    container_port=p_num,
                                    protocol=proto,
                                )
                            )

                    health_status = c.attrs.get("State", {}).get("Health", {}).get("Status")

                    containers_list.append(
                        ContainerInfo(
                            id=c.short_id,
                            name=str(c.name or "unknown"),
                            image=(
                                c.image.tags[0]
                                if (c.image and c.image.tags)
                                else str(c.image.id if c.image else "unknown")
                            ),
                            status=c.status,
                            state=c.attrs.get("State", {}).get("Status", c.status),
                            health=health_status,
                            created_at=c.attrs.get("Created"),
                            ports=ports,
                            labels=c.labels or {},
                        )
                    )

                images_list: list[ImageInfo] = []
                try:
                    for img in client.images.list()[:10]:
                        images_list.append(
                            ImageInfo(
                                id=img.short_id,
                                tags=img.tags or [],
                                size_bytes=img.attrs.get("Size", 0),
                                created_at=img.attrs.get("Created"),
                            )
                        )
                except Exception:
                    pass

                networks_list: list[NetworkInfo] = []
                try:
                    for net in client.networks.list()[:10]:
                        networks_list.append(
                            NetworkInfo(
                                id=net.short_id,
                                name=str(net.name or "unknown"),
                                driver=net.attrs.get("Driver", "bridge"),
                                scope=net.attrs.get("Scope", "local"),
                                containers=list(net.attrs.get("Containers", {}).keys()),
                            )
                        )
                except Exception:
                    pass

                volumes_list: list[VolumeInfo] = []
                try:
                    for vol in client.volumes.list()[:10]:
                        volumes_list.append(
                            VolumeInfo(
                                name=vol.name,
                                driver=vol.attrs.get("Driver", "local"),
                                mountpoint=vol.attrs.get("Mountpoint", ""),
                            )
                        )
                except Exception:
                    pass

                client.close()
                return DockerSnapshot(
                    is_available=True,
                    server_version=server_ver,
                    containers=containers_list,
                    images=images_list,
                    networks=networks_list,
                    volumes=volumes_list,
                )
            except Exception as exc:
                logger.debug("No fue posible conectar con Docker vía SDK: %s", exc)
                return DockerSnapshot(
                    is_available=False,
                    error_message=f"Docker no accesible vía SDK: {exc}",
                )

        # 2. Si docker SDK no está instalado, comprobar presencia de socket
        socket_path = Path(self._docker_socket_path)
        if not socket_path.exists():
            return DockerSnapshot(
                is_available=False,
                error_message=f"Socket Docker no encontrado en {self._docker_socket_path}",
            )

        return DockerSnapshot(
            is_available=False,
            error_message="Socket Docker detectado pero SDK 'docker' no disponible en entorno",
        )

    def _collect_k8s_info(self) -> KubernetesSnapshot:
        """Comprueba si el entorno se encuentra dentro o conectado a un clúster Kubernetes."""
        token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        kubeconfig = os.getenv("KUBECONFIG")

        if not token_path.exists() and not kubeconfig:
            return KubernetesSnapshot(
                is_available=False,
                error_message="Entorno Kubernetes no detectado (sin in-cluster token ni KUBECONFIG)",
            )

        return KubernetesSnapshot(
            is_available=False,
            cluster_name="unknown",
            error_message="Entorno K8s detectado pero cliente API no configurado",
        )

    def _detect_incidents(
        self,
        host: HostSnapshot,
        docker_snap: DockerSnapshot,
        k8s_snap: KubernetesSnapshot,
    ) -> list[InfraIncident]:
        """Detecta incidentes y anomalías tempranas a partir de la telemetría recolectada."""
        incidents: list[InfraIncident] = []

        # 1. Alertas de CPU del Host
        if host.cpu and host.cpu.usage_percent >= 90.0:
            incidents.append(
                InfraIncident(
                    severity=IncidentSeverity.HIGH,
                    title="Uso de CPU crítico en el Host",
                    component="host",
                    description=(
                        f"El uso de CPU alcanzó {host.cpu.usage_percent}% "
                        f"(cores lógicos: {host.cpu.cores_logical})"
                    ),
                    details={
                        "usage_percent": host.cpu.usage_percent,
                        "cores": host.cpu.cores_logical,
                    },
                )
            )

        # 2. Alertas de Memoria del Host
        if host.memory and host.memory.percent >= 90.0:
            incidents.append(
                InfraIncident(
                    severity=IncidentSeverity.HIGH,
                    title="Memoria RAM saturada en el Host",
                    component="host",
                    description=(
                        f"El uso de memoria RAM es de {host.memory.percent}% "
                        f"({round(host.memory.used_bytes / (1024**3), 2)} GB ocupados de "
                        f"{round(host.memory.total_bytes / (1024**3), 2)} GB)"
                    ),
                    details={
                        "memory_percent": host.memory.percent,
                        "used_bytes": host.memory.used_bytes,
                        "total_bytes": host.memory.total_bytes,
                    },
                )
            )

        # 3. Alertas de Almacenamiento en Disco
        for disk in host.disks:
            if disk.percent >= 90.0:
                incidents.append(
                    InfraIncident(
                        severity=IncidentSeverity.HIGH,
                        title=f"Espacio en disco crítico en {disk.mountpoint}",
                        component="host",
                        description=(
                            f"La partición {disk.mountpoint} ({disk.device}) está al {disk.percent}% "
                            f"({round(disk.free_bytes / (1024**3), 2)} GB disponibles)"
                        ),
                        details={
                            "mountpoint": disk.mountpoint,
                            "percent": disk.percent,
                            "free_bytes": disk.free_bytes,
                        },
                    )
                )

        # 4. Alertas de Contenedores Docker caídos o unhealthy
        if docker_snap.is_available:
            for container in docker_snap.containers:
                if container.health == "unhealthy":
                    incidents.append(
                        InfraIncident(
                            severity=IncidentSeverity.HIGH,
                            title=f"Contenedor unhealthy: {container.name}",
                            component="docker",
                            description=f"El healthcheck del contenedor '{container.name}' reporta estado 'unhealthy'.",
                            details={"container_id": container.id, "image": container.image},
                        )
                    )
                elif container.state in ("exited", "dead") and "Exited (0)" not in container.status:
                    incidents.append(
                        InfraIncident(
                            severity=IncidentSeverity.MEDIUM,
                            title=f"Contenedor detenido de forma anómala: {container.name}",
                            component="docker",
                            description=f"El contenedor '{container.name}' está en estado '{container.state}' ({container.status}).",
                            details={"container_id": container.id, "status": container.status},
                        )
                    )

        return incidents
