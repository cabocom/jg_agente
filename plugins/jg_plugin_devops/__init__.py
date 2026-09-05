"""Paquete jg_plugin_devops para jg_agente.

Provee capacidades de gestión, observabilidad y operación de infraestructura
cumpliendo el contrato formal BasePlugin del Execution Plane.
"""

from jg_plugin_devops.models.db import (
    DevopsBase,
    DevopsIncident,
    DevopsSnapshot,
)
from jg_plugin_devops.models.snapshot import (
    ContainerInfo,
    CPUInfo,
    DeploymentInfo,
    DiskPartitionInfo,
    DockerSnapshot,
    HostSnapshot,
    IncidentSeverity,
    InfraIncident,
    InfraSnapshot,
    KubernetesSnapshot,
    MemoryInfo,
    OSInfo,
    PodInfo,
    PortInfo,
    ProcessInfo,
    ServiceInfo,
)
from jg_plugin_devops.plugin import DevOpsPlugin

PLUGIN_CLASS = DevOpsPlugin
__version__ = "0.1.0"

__all__ = [
    "DevOpsPlugin",
    "PLUGIN_CLASS",
    "__version__",
    # Modelos Pydantic
    "InfraSnapshot",
    "HostSnapshot",
    "DockerSnapshot",
    "KubernetesSnapshot",
    "InfraIncident",
    "IncidentSeverity",
    "OSInfo",
    "CPUInfo",
    "MemoryInfo",
    "DiskPartitionInfo",
    "ProcessInfo",
    "ServiceInfo",
    "PortInfo",
    "ContainerInfo",
    "PodInfo",
    "DeploymentInfo",
    # Modelos SQLAlchemy
    "DevopsBase",
    "DevopsSnapshot",
    "DevopsIncident",
]
