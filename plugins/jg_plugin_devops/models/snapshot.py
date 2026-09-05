"""Modelos de dominio Pydantic v2 para capturas y telemetría de infraestructura.

Define esquemas fuertemente tipados para Host, Docker, Kubernetes e Incidentes,
garantizando el aislamiento completo del Core de jg_agente.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IncidentSeverity(StrEnum):
    """Niveles de severidad estandarizados para incidentes de infraestructura."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# ============================================================================
# 1. Componentes del Host (Sistema Operativo, Hardware y Procesos)
# ============================================================================


class OSInfo(BaseModel):
    """Información del sistema operativo del host."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Nombre del SO (e.g. Linux, Darwin, Windows)")
    version: str = Field(default="", description="Versión o release de la distribución")
    kernel: str = Field(default="", description="Versión del kernel en ejecución")
    arch: str = Field(default="", description="Arquitectura de hardware (e.g. x86_64, aarch64)")
    uptime_seconds: float | None = Field(
        default=None, description="Segundos transcurridos desde el arranque"
    )


class CPUInfo(BaseModel):
    """Métricas y capacidades de procesamiento de la CPU."""

    model_config = ConfigDict(extra="ignore")

    cores_logical: int = Field(ge=1, description="Número de núcleos lógicos (vCPUs)")
    cores_physical: int | None = Field(default=None, ge=1, description="Número de núcleos físicos")
    usage_percent: float = Field(ge=0.0, le=100.0, description="Porcentaje de uso global de CPU")
    load_average: list[float] = Field(
        default_factory=list,
        description="Medias de carga de trabajo [1m, 5m, 15m] si están disponibles",
    )


class MemoryInfo(BaseModel):
    """Métricas de memoria RAM del host."""

    model_config = ConfigDict(extra="ignore")

    total_bytes: int = Field(ge=0, description="Total de memoria en bytes")
    available_bytes: int = Field(
        ge=0, description="Memoria disponible para nuevas aplicaciones en bytes"
    )
    used_bytes: int = Field(ge=0, description="Memoria actualmente utilizada en bytes")
    percent: float = Field(ge=0.0, le=100.0, description="Porcentaje de uso de memoria")


class DiskPartitionInfo(BaseModel):
    """Estado y utilización de un volumen o partición de disco."""

    model_config = ConfigDict(extra="ignore")

    mountpoint: str = Field(description="Punto de montaje (e.g. '/', '/var')")
    device: str = Field(description="Dispositivo de bloque o identificador de disco")
    fstype: str = Field(default="", description="Tipo de sistema de archivos (e.g. ext4, apfs)")
    total_bytes: int = Field(ge=0, description="Capacidad total de la partición en bytes")
    used_bytes: int = Field(ge=0, description="Espacio ocupado en bytes")
    free_bytes: int = Field(ge=0, description="Espacio libre disponible en bytes")
    percent: float = Field(ge=0.0, le=100.0, description="Porcentaje de ocupación")


class ProcessInfo(BaseModel):
    """Detalle de un proceso en ejecución relevante o de alto consumo."""

    model_config = ConfigDict(extra="ignore")

    pid: int = Field(description="Identificador numérico del proceso (PID)")
    name: str = Field(description="Nombre del ejecutable o proceso")
    status: str = Field(
        default="running", description="Estado del proceso (running, sleeping, zombie, etc.)"
    )
    cpu_percent: float = Field(default=0.0, ge=0.0, description="Porcentaje de CPU consumido")
    memory_percent: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Porcentaje de memoria consumido"
    )
    cmdline: list[str] = Field(default_factory=list, description="Línea de comandos con argumentos")


class ServiceInfo(BaseModel):
    """Estado de un servicio o daemon del sistema (systemd, launchd, etc.)."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Nombre del servicio (e.g. nginx, docker, ssh)")
    state: str = Field(description="Estado actual del servicio (e.g. active, inactive, failed)")
    enabled: bool | None = Field(
        default=None, description="Indica si el servicio inicia con el sistema"
    )
    description: str = Field(default="", description="Descripción legible del servicio")


class PortInfo(BaseModel):
    """Puerto de red en escucha o activo."""

    model_config = ConfigDict(extra="ignore")

    port: int = Field(ge=1, le=65535, description="Número de puerto")
    protocol: str = Field(default="tcp", description="Protocolo (tcp, udp)")
    state: str = Field(default="LISTEN", description="Estado del socket de red")
    process: str | None = Field(default=None, description="Nombre del proceso que ocupa el puerto")
    pid: int | None = Field(default=None, description="PID del proceso vinculado")


class HostSnapshot(BaseModel):
    """Fotografía completa del estado del servidor / máquina anfitriona."""

    model_config = ConfigDict(extra="ignore")

    hostname: str = Field(description="Nombre de red del host")
    os: OSInfo | None = Field(default=None, description="Información del sistema operativo")
    cpu: CPUInfo | None = Field(default=None, description="Métricas de CPU")
    memory: MemoryInfo | None = Field(default=None, description="Métricas de memoria")
    disks: list[DiskPartitionInfo] = Field(
        default_factory=list, description="Particiones de almacenamiento"
    )
    top_processes: list[ProcessInfo] = Field(
        default_factory=list, description="Procesos principales"
    )
    services: list[ServiceInfo] = Field(default_factory=list, description="Servicios auditados")
    listening_ports: list[PortInfo] = Field(default_factory=list, description="Puertos en escucha")


# ============================================================================
# 2. Componentes de Docker (Contenedores, Imágenes, Redes, Volúmenes)
# ============================================================================


class ContainerPortInfo(BaseModel):
    """Mapeo de puertos de red de un contenedor Docker."""

    model_config = ConfigDict(extra="ignore")

    container_port: int = Field(ge=1, le=65535, description="Puerto interno del contenedor")
    protocol: str = Field(default="tcp", description="Protocolo (tcp, udp)")
    host_ip: str | None = Field(default=None, description="IP del host asociada")
    host_port: int | None = Field(
        default=None, ge=1, le=65535, description="Puerto expuesto en el host"
    )


class ContainerInfo(BaseModel):
    """Información detallada de un contenedor Docker."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Identificador único del contenedor (hash o corto)")
    name: str = Field(description="Nombre legible del contenedor")
    image: str = Field(description="Imagen y tag utilizados")
    status: str = Field(description="Estado de ejecución (e.g. 'Up 2 hours', 'Exited (0)')")
    state: str = Field(description="Estado simple (running, exited, paused, restarting)")
    health: str | None = Field(
        default=None, description="Estado de healthcheck si existe (healthy, unhealthy)"
    )
    created_at: str | None = Field(default=None, description="Fecha de creación ISO")
    ports: list[ContainerPortInfo] = Field(default_factory=list, description="Puertos mapeados")
    labels: dict[str, str] = Field(default_factory=dict, description="Etiquetas Docker")


class ImageInfo(BaseModel):
    """Detalle de una imagen de contenedor en el host."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Identificador de la imagen")
    tags: list[str] = Field(default_factory=list, description="Repositorios y tags asociados")
    size_bytes: int = Field(default=0, ge=0, description="Tamaño virtual en bytes")
    created_at: str | None = Field(default=None, description="Fecha de creación ISO")


class NetworkInfo(BaseModel):
    """Red Docker configurada en el motor."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Identificador de la red")
    name: str = Field(description="Nombre de la red")
    driver: str = Field(default="bridge", description="Driver (bridge, overlay, host, none)")
    scope: str = Field(default="local", description="Alcance de la red")
    containers: list[str] = Field(
        default_factory=list, description="IDs o nombres de contenedores conectados"
    )


class VolumeInfo(BaseModel):
    """Volumen de almacenamiento persistente Docker."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Nombre único del volumen")
    driver: str = Field(default="local", description="Driver del volumen")
    mountpoint: str = Field(default="", description="Ruta absoluta en el host")


class DockerSnapshot(BaseModel):
    """Fotografía completa del subsistema Docker."""

    model_config = ConfigDict(extra="ignore")

    is_available: bool = Field(
        default=False, description="Indica si el daemon Docker respondió correctamente"
    )
    server_version: str | None = Field(default=None, description="Versión del motor Docker")
    containers: list[ContainerInfo] = Field(
        default_factory=list, description="Contenedores detectados"
    )
    images: list[ImageInfo] = Field(default_factory=list, description="Imágenes almacenadas")
    networks: list[NetworkInfo] = Field(default_factory=list, description="Redes activas")
    volumes: list[VolumeInfo] = Field(default_factory=list, description="Volúmenes configurados")
    error_message: str | None = Field(
        default=None, description="Mensaje de error si la conexión falló"
    )


# ============================================================================
# 3. Componentes de Kubernetes (Pods, Deployments, Services, Ingresses, Events)
# ============================================================================


class PodInfo(BaseModel):
    """Información de un Pod en el clúster de Kubernetes."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Nombre del Pod")
    namespace: str = Field(default="default", description="Namespace donde reside")
    phase: str = Field(
        description="Fase del ciclo de vida (Pending, Running, Succeeded, Failed, Unknown)"
    )
    ready: bool = Field(default=False, description="Indica si todos sus contenedores están listos")
    restarts: int = Field(default=0, ge=0, description="Número de reinicios acumulados")
    node_name: str | None = Field(default=None, description="Nodo donde está programado")
    created_at: str | None = Field(default=None, description="Timestamp de creación ISO")


class DeploymentInfo(BaseModel):
    """Estado de un recurso Deployment de Kubernetes."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Nombre del Deployment")
    namespace: str = Field(default="default", description="Namespace")
    replicas: int = Field(default=1, ge=0, description="Réplicas deseadas")
    ready_replicas: int = Field(default=0, ge=0, description="Réplicas listas y operativas")
    updated_replicas: int = Field(
        default=0, ge=0, description="Réplicas actualizadas a la última versión"
    )
    available_replicas: int = Field(default=0, ge=0, description="Réplicas disponibles")


class K8sServiceInfo(BaseModel):
    """Detalle de un Service de Kubernetes."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Nombre del Service")
    namespace: str = Field(default="default", description="Namespace")
    type: str = Field(
        default="ClusterIP", description="Tipo (ClusterIP, NodePort, LoadBalancer, ExternalName)"
    )
    cluster_ip: str | None = Field(default=None, description="IP interna del clúster")
    external_ip: str | None = Field(default=None, description="IP o hostname externo si aplica")
    ports: list[dict[str, Any]] = Field(
        default_factory=list, description="Definición de puertos del servicio"
    )


class IngressInfo(BaseModel):
    """Regla de entrada Ingress de Kubernetes."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Nombre del Ingress")
    namespace: str = Field(default="default", description="Namespace")
    hosts: list[str] = Field(default_factory=list, description="Hostnames enrutados")


class K8sEventInfo(BaseModel):
    """Evento relevante o advertencia registrada en el clúster."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Identificador o nombre del evento")
    namespace: str = Field(default="default", description="Namespace")
    reason: str = Field(description="Razón estandarizada (e.g. FailedScheduling, BackOff, Pulled)")
    message: str = Field(description="Mensaje descriptivo del evento")
    type: str = Field(default="Normal", description="Tipo de evento (Normal, Warning)")
    count: int = Field(default=1, ge=1, description="Ocurrencias del evento")
    last_timestamp: str | None = Field(default=None, description="Última marca temporal registrada")


class KubernetesSnapshot(BaseModel):
    """Fotografía del estado del clúster Kubernetes."""

    model_config = ConfigDict(extra="ignore")

    is_available: bool = Field(
        default=False, description="Indica si la API de Kubernetes es accesible"
    )
    cluster_name: str | None = Field(default=None, description="Nombre o contexto del clúster")
    server_version: str | None = Field(default=None, description="Versión del API Server")
    namespaces: list[str] = Field(default_factory=list, description="Namespaces descubiertos")
    pods: list[PodInfo] = Field(default_factory=list, description="Pods consultados")
    deployments: list[DeploymentInfo] = Field(
        default_factory=list, description="Deployments consultados"
    )
    services: list[K8sServiceInfo] = Field(
        default_factory=list, description="Servicios consultados"
    )
    ingresses: list[IngressInfo] = Field(default_factory=list, description="Reglas Ingress")
    recent_events: list[K8sEventInfo] = Field(
        default_factory=list, description="Eventos recientes de interés"
    )
    error_message: str | None = Field(
        default=None, description="Error al conectar con la API de Kubernetes"
    )


# ============================================================================
# 4. Incidentes y Anomalías Detectadas
# ============================================================================


class InfraIncident(BaseModel):
    """Incidente o anomalía detectada en la infraestructura."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Identificador único del incidente",
    )
    severity: IncidentSeverity = Field(
        default=IncidentSeverity.MEDIUM,
        description="Nivel de severidad del incidente",
    )
    title: str = Field(description="Título sintético del incidente")
    component: str = Field(
        description="Subsistema o componente afectado (e.g. host, docker, postgres, k8s)"
    )
    description: str = Field(
        default="", description="Explicación detallada de la anomalía observada"
    )
    details: dict[str, Any] = Field(default_factory=dict, description="Datos técnicos contextuales")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Marca temporal UTC de detección",
    )
    resolved: bool = Field(
        default=False, description="Indica si la anomalía fue resuelta o mitigada"
    )


# ============================================================================
# 5. Contenedor Maestro de Infraestructura (InfraSnapshot)
# ============================================================================


class InfraSnapshot(BaseModel):
    """Modelo consolidado de captura y estado de toda la infraestructura observada.

    Encapsula el estado del Host, Docker, Kubernetes y anomalías detectadas,
    así como proyecciones rápidas para motores de planificación y razonamiento.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Identificador único de la captura",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Marca temporal UTC de la captura",
    )
    host: HostSnapshot | None = Field(
        default=None,
        description="Telemetría y estado del host anfitrión",
    )
    docker: DockerSnapshot | None = Field(
        default=None,
        description="Estado y contenedores del motor Docker",
    )
    kubernetes: KubernetesSnapshot | None = Field(
        default=None,
        description="Estado de los recursos en Kubernetes",
    )
    incidents: list[InfraIncident] = Field(
        default_factory=list,
        description="Incidentes o anomalías identificadas en esta captura",
    )
    host_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Métricas resumidas de rendimiento del host (cpu, mem, disk)",
    )
    containers: dict[str, str] = Field(
        default_factory=dict,
        description="Mapa rápido de nombre_contenedor -> estado_ejecución",
    )
    services: dict[str, str] = Field(
        default_factory=dict,
        description="Mapa rápido de nombre_servicio -> estado_ejecución",
    )
    topology: dict[str, Any] = Field(
        default_factory=dict,
        description="Relaciones topológicas descubiertas entre componentes",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos libres asociados a la captura",
    )
    summary: str | None = Field(
        default=None,
        description="Resumen narrativo o diagnóstico de la captura",
    )
