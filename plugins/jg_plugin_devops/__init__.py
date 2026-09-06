"""Paquete jg_plugin_devops para jg_agente.

Provee capacidades de gestión, observabilidad y operación de infraestructura
cumpliendo el contrato formal BasePlugin del Execution Plane.
"""

from jg_plugin_devops.discovery import InfraDiscoveryEngine
from jg_plugin_devops.docker_tools import (
    DockerInspectContainerArgs,
    DockerInspectContainerTool,
    DockerListContainersArgs,
    DockerListContainersTool,
    DockerRestartArgs,
    DockerRestartTool,
    create_docker_inspect_container_tool,
    create_docker_list_containers_tool,
    create_docker_restart_tool,
)
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
from jg_plugin_devops.planner import DAGPlannerEngine
from jg_plugin_devops.plugin import DevOpsPlugin
from jg_plugin_devops.verifier import DevopsVerifierEngine

PLUGIN_CLASS = DevOpsPlugin
__version__ = "0.1.0"

__all__ = [
    "DevOpsPlugin",
    "InfraDiscoveryEngine",
    "DAGPlannerEngine",
    "DevopsVerifierEngine",
    "DockerRestartTool",
    "DockerRestartArgs",
    "create_docker_restart_tool",
    "DockerListContainersTool",
    "DockerListContainersArgs",
    "create_docker_list_containers_tool",
    "DockerInspectContainerTool",
    "DockerInspectContainerArgs",
    "create_docker_inspect_container_tool",
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
