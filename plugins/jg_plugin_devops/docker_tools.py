"""Herramientas de gestión y ciclo de vida de Docker para jg_plugin_devops.

Implementa DockerRestartTool bajo el contrato canónico AgentTool con nivel de riesgo
RiskLevel.HIGH, reversible=True, preservación de rollback_context y función de compensación.
"""

import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.tools import AgentTool, RiskLevel, ToolResult, ToolType

logger = logging.getLogger("jg_plugin_devops.docker_tools")

# Regex de seguridad para nombres e identificadores de contenedores Docker
# Admite nombres canónicos Docker (letras, dígitos, guiones, puntos y barras bajas)
# o IDs hexadecimales (12 a 64 caracteres). Bloquea inyecciones de comandos y metacaracteres.
CONTAINER_NAME_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")

# Contenedores de infraestructura de seguridad protegidos contra manipulación por el agente
PROTECTED_INFRASTRUCTURE_CONTAINERS: frozenset[str] = frozenset(
    {
        "jg_docker_socket_proxy",
        "docker_socket_proxy",
    }
)

docker: Any
try:
    import docker
    from docker.errors import DockerException, NotFound
except ImportError:
    docker = None
    DockerException = Exception  # type: ignore[misc,assignment]
    NotFound = Exception  # type: ignore[misc,assignment]


_custom_docker_client: Any = None


def set_docker_client(client: Any) -> None:
    """Permite inyectar o mockear un cliente Docker para pruebas unitarias o simulación."""
    global _custom_docker_client
    _custom_docker_client = client


def get_docker_client() -> Any:
    """Obtiene el cliente de Docker activo o None si no está disponible.

    Prioriza la variable DOCKER_HOST cuando está configurada en el entorno
    (por ejemplo, proxy seguro tecnativa/docker-socket-proxy) y recurre a from_env().
    """
    global _custom_docker_client
    if _custom_docker_client is not None:
        return _custom_docker_client
    if docker is not None:
        try:
            docker_host = os.getenv("DOCKER_HOST")
            if docker_host:
                return docker.DockerClient(base_url=docker_host, timeout=5)
            return docker.from_env(timeout=5)
        except Exception as exc:
            logger.debug("Daemon de Docker no disponible vía socket o proxy: %s", exc)
            return None
    return None


class DockerRestartArgs(BaseModel):
    """Argumentos de entrada validados para el reinicio de contenedores Docker."""

    container: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Nombre o identificador (ID/short_id) del contenedor Docker a reiniciar. "
            "Ej: 'jg_dashboard', 'devops60k_web', '308ad84dec86'."
        ),
    )
    timeout: int = Field(
        default=10,
        ge=1,
        le=120,
        description="Tiempo de espera en segundos antes de forzar el apagado (SIGKILL tras SIGTERM).",
    )

    @field_validator("container")
    @classmethod
    def validate_safe_container(cls, value: str) -> str:
        cleaned = value.strip().lstrip("/")
        if not cleaned:
            raise ValueError("El identificador del contenedor no puede estar vacío.")

        # Prevención de inyecciones de comandos y caracteres peligrosos
        if not CONTAINER_NAME_REGEX.match(cleaned):
            raise ValueError(
                f"Nombre o ID de contenedor no permitido: '{cleaned}'. "
                "Solo se permiten caracteres alfanuméricos, guiones, puntos y guiones bajos."
            )

        # Protección de componentes de seguridad de infraestructura
        if cleaned.lower() in PROTECTED_INFRASTRUCTURE_CONTAINERS:
            raise ValueError(
                f"El contenedor '{cleaned}' es un componente de seguridad protegido de la infraestructura y no puede ser manipulado."
            )

        return cleaned


def restart_container_fn(
    args: DockerRestartArgs | None = None,
    container: str | None = None,
    timeout: int = 10,
    **kwargs: Any,
) -> ToolResult:
    """Ejecuta el reinicio de un contenedor Docker capturando el estado previo para compensación."""
    start_time = time.perf_counter()

    if args is None:
        raw_target = (
            container
            or kwargs.get("container_name")
            or kwargs.get("name")
            or kwargs.get("title")
            or kwargs.get("input")
            or ""
        )
        try:
            args = DockerRestartArgs(container=str(raw_target), timeout=timeout)
        except Exception as exc:
            duration = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ToolResult(
                success=False,
                output="",
                error=f"Argumentos inválidos para docker_restart: {exc}",
                duration_ms=duration,
            )

    target_name = args.container
    target_timeout = args.timeout

    # Protección de componentes de seguridad de infraestructura
    if target_name.lower() in PROTECTED_INFRASTRUCTURE_CONTAINERS:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=(
                f"El contenedor '{target_name}' es un componente de seguridad protegido "
                "de la infraestructura y no puede ser manipulado."
            ),
            duration_ms=duration,
        )

    # 1. Modo simulación si está configurado explícitamente en el entorno
    is_simulated_env = os.getenv("DOCKER_SIMULATION_MODE", "").lower() in ("true", "1", "yes")
    if is_simulated_env:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=True,
            output=f"Contenedor '{target_name}' reiniciado exitosamente (modo simulado).",
            duration_ms=duration,
            rollback_context={
                "container": target_name,
                "container_id": f"sim-{target_name[:12]}",
                "previous_state": "running",
                "action": "restart",
                "simulation": True,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            metadata={
                "container": target_name,
                "previous_state": "running",
                "current_state": "running",
                "simulation": True,
            },
        )

    client = get_docker_client()

    if client is None:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=(
                f"No fue posible conectar con el daemon de Docker para reiniciar '{target_name}'. "
                "Verifique que el servicio Docker está activo y el socket es accesible."
            ),
            duration_ms=duration,
        )

    # 2. Inspección del estado pre-operacional
    try:
        c = client.containers.get(target_name)
        prev_status = getattr(c, "status", "unknown")
        container_id = str(getattr(c, "id", target_name))
        container_name = str(getattr(c, "name", target_name))
    except NotFound:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"No se encontró el contenedor Docker '{target_name}'.",
            duration_ms=duration,
        )
    except Exception as exc:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"Error al inspeccionar estado de '{target_name}': {exc}",
            duration_ms=duration,
        )

    # 3. Ejecución del reinicio
    try:
        c.restart(timeout=target_timeout)
        if hasattr(c, "reload"):
            c.reload()
        current_status = getattr(c, "status", "running")
    except Exception as exc:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"Fallo al ejecutar reinicio de contenedor '{container_name}': {exc}",
            duration_ms=duration,
            rollback_context={
                "container": container_name,
                "container_id": container_id,
                "previous_state": prev_status,
                "action": "restart",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    duration = round((time.perf_counter() - start_time) * 1000.0, 2)
    return ToolResult(
        success=True,
        output=(
            f"Contenedor '{container_name}' ({container_id[:12]}) reiniciado exitosamente. "
            f"Estado previo: '{prev_status}', estado actual: '{current_status}'."
        ),
        duration_ms=duration,
        rollback_context={
            "container": container_name,
            "container_id": container_id,
            "previous_state": prev_status,
            "post_state": current_status,
            "action": "restart",
            "timestamp": datetime.now(UTC).isoformat(),
        },
        metadata={
            "container": container_name,
            "container_id": container_id,
            "previous_state": prev_status,
            "current_state": current_status,
        },
    )


def rollback_restart_container_fn(rollback_context: dict[str, Any]) -> ToolResult:
    """Restaura el estado original del contenedor en caso de fallo en pasos posteriores del plan."""
    start_time = time.perf_counter()

    if not isinstance(rollback_context, dict):
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error="Contexto de rollback inválido: se esperaba un diccionario con los datos del estado previo.",
            duration_ms=duration,
        )

    container_ref = rollback_context.get("container") or rollback_context.get("container_id")
    if not container_ref:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error="Contexto de rollback incompleto: falta 'container' o 'container_id'.",
            duration_ms=duration,
        )

    prev_state = rollback_context.get("previous_state", "running")
    is_simulated = rollback_context.get("simulation", False)

    # Compensación para ejecuciones simuladas
    if is_simulated or os.getenv("DOCKER_SIMULATION_MODE", "").lower() in ("true", "1", "yes"):
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=True,
            output=f"Compensación simulada: Contenedor '{container_ref}' restaurado al estado previo '{prev_state}'.",
            duration_ms=duration,
            metadata={
                "container": container_ref,
                "restored_state": prev_state,
                "simulation": True,
                "rollback_executed": True,
            },
        )

    client = get_docker_client()
    if client is None:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"No fue posible conectar con Docker para compensar el contenedor '{container_ref}'.",
            duration_ms=duration,
        )

    try:
        c = client.containers.get(container_ref)

        # Caso A: Si el contenedor estaba detenido o caído antes del reinicio, se detiene
        if prev_state in ("exited", "stopped", "dead", "created"):
            logger.warning(
                "Rollback compensatorio: deteniendo contenedor '%s' para restaurar estado previo '%s'",
                container_ref,
                prev_state,
            )
            c.stop(timeout=10)
            if hasattr(c, "reload"):
                c.reload()
            curr = getattr(c, "status", "exited")
            duration = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ToolResult(
                success=True,
                output=(
                    f"Compensación completada: Contenedor '{container_ref}' detenido para "
                    f"restaurar estado previo '{prev_state}' (estado actual: '{curr}')."
                ),
                duration_ms=duration,
                metadata={
                    "container": container_ref,
                    "target_state": prev_state,
                    "current_state": curr,
                    "rollback_executed": True,
                },
            )

        # Caso B: Si estaba pausado, se vuelve a pausar
        elif prev_state == "paused":
            logger.warning(
                "Rollback compensatorio: pausando contenedor '%s' para restaurar estado previo 'paused'",
                container_ref,
            )
            c.pause()
            if hasattr(c, "reload"):
                c.reload()
            curr = getattr(c, "status", "paused")
            duration = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ToolResult(
                success=True,
                output=(
                    f"Compensación completada: Contenedor '{container_ref}' pausado para "
                    f"restaurar estado previo '{prev_state}' (estado actual: '{curr}')."
                ),
                duration_ms=duration,
                metadata={
                    "container": container_ref,
                    "target_state": prev_state,
                    "current_state": curr,
                    "rollback_executed": True,
                },
            )

        # Caso C: Si estaba en ejecución (running), se verifica y asegura su operatividad
        else:
            if hasattr(c, "reload"):
                c.reload()
            curr = getattr(c, "status", "running")
            duration = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ToolResult(
                success=True,
                output=(
                    f"Compensación completada: Contenedor '{container_ref}' verificado en ejecución "
                    f"para preservar estado previo '{prev_state}' (estado actual: '{curr}')."
                ),
                duration_ms=duration,
                metadata={
                    "container": container_ref,
                    "target_state": prev_state,
                    "current_state": curr,
                    "rollback_executed": True,
                },
            )

    except NotFound:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"No se encontró el contenedor '{container_ref}' durante la compensación de rollback.",
            duration_ms=duration,
        )
    except Exception as exc:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"Error durante la compensación (rollback) del contenedor '{container_ref}': {exc}",
            duration_ms=duration,
        )


class DockerRestartTool(AgentTool):
    """Herramienta para reinicio seguro de contenedores Docker con compensación automática."""

    def __init__(self, **data: Any) -> None:
        defaults: dict[str, Any] = {
            "name": "docker_restart",
            "description": (
                "Reinicia un contenedor Docker identificado por nombre o ID, "
                "capturando su estado previo para permitir reversibilidad y compensación."
            ),
            "category": "devops",
            "version": "0.1.0",
            "args_schema": DockerRestartArgs,
            "func": restart_container_fn,
            "risk_level": RiskLevel.HIGH,
            "required_permissions": ["docker:restart"],
            "tool_type": ToolType.ACTUATOR,
            "read_only": False,
            "reversible": True,
            "idempotent": False,
            "makes_http_requests": False,
            "timeout_sec": 60.0,
            "rollback_func": rollback_restart_container_fn,
        }
        defaults.update(data)
        super().__init__(**defaults)


def create_docker_restart_tool(**overrides: Any) -> AgentTool:
    """Factoría canónica para instanciar DockerRestartTool bajo el contrato AgentTool."""
    return DockerRestartTool(**overrides)


class DockerListContainersArgs(BaseModel):
    """Esquema de argumentos para listar contenedores Docker."""

    all: bool = Field(
        default=True,
        description="Si es True enumera todos los contenedores (activos y parados); si es False solo los activos.",
    )


def _extract_image_identifier(c: Any) -> str:
    """Extrae de forma segura el tag o identificador de imagen sin romper ante proxies restringidos."""
    attrs = getattr(c, "attrs", {})
    img_from_attrs = ""
    if isinstance(attrs, dict):
        img_from_attrs = attrs.get("Config", {}).get("Image") or attrs.get("Image") or ""
    try:
        if hasattr(c, "image") and c.image is not None:
            tags = getattr(c.image, "tags", None)
            if tags and len(tags) > 0:
                return str(tags[0])
            short_id = getattr(c.image, "short_id", getattr(c.image, "id", None))
            if short_id:
                return str(short_id)
    except Exception:
        pass

    return str(img_from_attrs or "unknown")


def list_containers_fn(
    args: DockerListContainersArgs | None = None,
    all: bool = True,
    **kwargs: Any,
) -> ToolResult:
    """Consulta y lista los contenedores Docker en el host."""
    start_time = time.perf_counter()
    show_all = args.all if args is not None else all

    is_simulated = os.getenv("DOCKER_SIMULATION_MODE", "").lower() in ("true", "1", "yes")
    if is_simulated:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        sim_containers = [
            {
                "id": "c1a2b3c4d5e6",
                "name": "jg_agente",
                "status": "running",
                "image": "jg_agente:latest",
            },
            {
                "id": "d2e3f4a5b6c7",
                "name": "jg_dashboard",
                "status": "running",
                "image": "jg_dashboard:latest",
            },
            {
                "id": "e3f4a5b6c7d8",
                "name": "jg_agente_postgres",
                "status": "running",
                "image": "postgres:16-alpine",
            },
            {
                "id": "f4a5b6c7d8e9",
                "name": "jg_dashboard_postgres",
                "status": "running",
                "image": "postgres:16-alpine",
            },
        ]
        return ToolResult(
            success=True,
            output=json.dumps(sim_containers, indent=2, ensure_ascii=False),
            duration_ms=duration,
        )

    client = get_docker_client()
    if client is None:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error="No fue posible conectar con el daemon de Docker. Verifique que el socket /var/run/docker.sock esté montado.",
            duration_ms=duration,
        )

    try:
        containers = client.containers.list(all=show_all)
        res_list = []
        for c in containers:
            img_tag = _extract_image_identifier(c)
            res_list.append(
                {
                    "id": str(getattr(c, "short_id", getattr(c, "id", ""))[:12]),
                    "name": str(getattr(c, "name", "")).lstrip("/"),
                    "status": str(getattr(c, "status", "unknown")),
                    "image": img_tag,
                }
            )
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=True,
            output=json.dumps(res_list, indent=2, ensure_ascii=False),
            duration_ms=duration,
        )
    except Exception as exc:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"Fallo al listar contenedores Docker: {exc}",
            duration_ms=duration,
        )


class DockerListContainersTool(AgentTool):
    """Herramienta para listar y consultar el estado de todos los contenedores Docker."""

    def __init__(self, **data: Any) -> None:
        defaults: dict[str, Any] = {
            "name": "docker_list_containers",
            "description": (
                "Lista y enumera los contenedores Docker en el host (id, nombre, imagen y estado). "
                "Permite saber qué contenedores están corriendo o caídos."
            ),
            "category": "devops",
            "version": "0.1.0",
            "args_schema": DockerListContainersArgs,
            "func": list_containers_fn,
            "risk_level": RiskLevel.LOW,
            "required_permissions": [],
            "tool_type": ToolType.READ,
            "read_only": True,
            "reversible": False,
            "idempotent": True,
            "makes_http_requests": False,
            "timeout_sec": 15.0,
        }
        defaults.update(data)
        super().__init__(**defaults)


def create_docker_list_containers_tool(**overrides: Any) -> AgentTool:
    """Factoría canónica para instanciar DockerListContainersTool."""
    return DockerListContainersTool(**overrides)


class DockerInspectContainerArgs(BaseModel):
    """Esquema de argumentos para inspeccionar un contenedor Docker específico."""

    container: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Nombre o identificador (ID/short_id) del contenedor Docker a inspeccionar. Ej: 'jg_agente', 'jg_dashboard'.",
    )

    @field_validator("container")
    @classmethod
    def validate_safe_container(cls, value: str) -> str:
        cleaned = value.strip().lstrip("/")
        if not cleaned:
            raise ValueError("El identificador del contenedor no puede estar vacío.")
        if not CONTAINER_NAME_REGEX.match(cleaned):
            raise ValueError(f"Nombre o ID de contenedor no permitido: '{cleaned}'.")
        return cleaned


def inspect_container_fn(
    args: DockerInspectContainerArgs | None = None,
    container: str | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Obtiene los detalles exhaustivos y telemetría de un contenedor Docker."""
    start_time = time.perf_counter()
    target = ""
    if args is not None:
        target = args.container
    else:
        target = str(
            container
            or kwargs.get("container_name")
            or kwargs.get("name")
            or kwargs.get("title")
            or ""
        )
    target = target.strip().lstrip("/")

    if not target:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error="El nombre o ID del contenedor es obligatorio para docker_inspect_container.",
            duration_ms=duration,
        )

    is_simulated = os.getenv("DOCKER_SIMULATION_MODE", "").lower() in ("true", "1", "yes")
    if is_simulated:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        sim_data = {
            "id": f"sim-{target[:12]}",
            "name": target,
            "status": "running",
            "image": f"{target}:latest",
            "state": {
                "status": "running",
                "running": True,
                "restarting": False,
                "health": "healthy",
            },
            "restart_count": 0,
            "created": datetime.now(UTC).isoformat(),
        }
        return ToolResult(
            success=True,
            output=json.dumps(sim_data, indent=2, ensure_ascii=False),
            duration_ms=duration,
        )

    client = get_docker_client()
    if client is None:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error="No fue posible conectar con el daemon de Docker. Verifique que el socket /var/run/docker.sock esté montado.",
            duration_ms=duration,
        )

    try:
        c = client.containers.get(target)
        attrs = getattr(c, "attrs", {})
        state_info = attrs.get("State", {})
        net_info = attrs.get("NetworkSettings", {}).get("Networks", {})
        img_name = _extract_image_identifier(c)

        details = {
            "id": str(getattr(c, "short_id", getattr(c, "id", ""))[:12]),
            "name": str(getattr(c, "name", target)).lstrip("/"),
            "status": str(getattr(c, "status", "unknown")),
            "created": attrs.get("Created", ""),
            "image": img_name,
            "state": {
                "status": state_info.get("Status", "unknown"),
                "running": state_info.get("Running", False),
                "restarting": state_info.get("Restarting", False),
                "exit_code": state_info.get("ExitCode", 0),
                "health": state_info.get("Health", {}).get("Status", "none"),
            },
            "restart_count": attrs.get("RestartCount", 0),
            "networks": list(net_info.keys()),
        }
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=True,
            output=json.dumps(details, indent=2, ensure_ascii=False),
            duration_ms=duration,
        )
    except NotFound:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"No se encontró el contenedor Docker '{target}'.",
            duration_ms=duration,
        )
    except Exception as exc:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"Fallo al inspeccionar contenedor '{target}': {exc}",
            duration_ms=duration,
        )


class DockerInspectContainerTool(AgentTool):
    """Herramienta para inspeccionar y obtener detalles técnicos de un contenedor Docker."""

    def __init__(self, **data: Any) -> None:
        defaults: dict[str, Any] = {
            "name": "docker_inspect_container",
            "description": (
                "Obtiene los detalles, configuración, estado de salud y telemetría de un contenedor Docker específico. "
                "Requiere el nombre o ID del contenedor a inspeccionar."
            ),
            "category": "devops",
            "version": "0.1.0",
            "args_schema": DockerInspectContainerArgs,
            "func": inspect_container_fn,
            "risk_level": RiskLevel.LOW,
            "required_permissions": [],
            "tool_type": ToolType.READ,
            "read_only": True,
            "reversible": False,
            "idempotent": True,
            "makes_http_requests": False,
            "timeout_sec": 15.0,
        }
        defaults.update(data)
        super().__init__(**defaults)


def create_docker_inspect_container_tool(**overrides: Any) -> AgentTool:
    """Factoría canónica para instanciar DockerInspectContainerTool."""
    return DockerInspectContainerTool(**overrides)


class DockerLogsArgs(BaseModel):
    """Esquema de argumentos para recuperar logs de un contenedor Docker."""

    container: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Nombre o identificador (ID/short_id) del contenedor Docker. Ej: 'jg_agente', 'jg_dashboard'.",
    )
    tail: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Número de últimas líneas de log a recuperar (por defecto 50, máximo 100).",
    )
    timestamps: bool = Field(
        default=False,
        description="Indica si se deben incluir las marcas de tiempo ISO en cada línea de log.",
    )

    @field_validator("container")
    @classmethod
    def validate_safe_container(cls, value: str) -> str:
        cleaned = value.strip().lstrip("/")
        if not cleaned:
            raise ValueError("El identificador del contenedor no puede estar vacío.")
        if not CONTAINER_NAME_REGEX.match(cleaned):
            raise ValueError(f"Nombre o ID de contenedor no permitido: '{cleaned}'.")
        return cleaned


def logs_container_fn(
    args: DockerLogsArgs | None = None,
    container: str | None = None,
    tail: int = 50,
    timestamps: bool = False,
    **kwargs: Any,
) -> ToolResult:
    """Obtiene los logs y trazas de salida de un contenedor Docker específico."""
    start_time = time.perf_counter()
    target = ""
    req_tail = tail
    req_timestamps = timestamps

    if args is not None:
        target = args.container
        req_tail = min(100, max(1, args.tail))
        req_timestamps = args.timestamps
    else:
        target = str(
            container
            or kwargs.get("container_name")
            or kwargs.get("name")
            or kwargs.get("title")
            or ""
        )
        if "tail" in kwargs:
            try:
                req_tail = max(1, min(100, int(kwargs["tail"])))
            except (ValueError, TypeError):
                req_tail = 50
        if "timestamps" in kwargs:
            req_timestamps = bool(kwargs["timestamps"])

    target = target.strip().lstrip("/")
    if not target:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error="El nombre o ID del contenedor es obligatorio para docker_logs.",
            duration_ms=duration,
        )

    # Modo simulación
    is_simulated = os.getenv("DOCKER_SIMULATION_MODE", "").lower() in ("true", "1", "yes")
    if is_simulated:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        sim_ts = f"{datetime.now(UTC).isoformat()} " if req_timestamps else ""
        sim_output = (
            f"{sim_ts}[INFO] Container '{target}' started successfully.\n"
            f"{sim_ts}[INFO] Healthcheck: status healthy (interval=30s).\n"
            f"{sim_ts}[INFO] Listening on standard ports. Ready to receive connections.\n"
            f"{sim_ts}[INFO] Active workers: 4, memory usage: 142MB / 512MB.\n"
            f"{sim_ts}[INFO] No uncaught exceptions or error signals detected in last {req_tail} lines."
        )
        return ToolResult(
            success=True,
            output=sim_output,
            duration_ms=duration,
        )

    client = get_docker_client()
    if client is None:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error="No fue posible conectar con el daemon de Docker. Verifique que el socket /var/run/docker.sock esté montado.",
            duration_ms=duration,
        )

    try:
        c = client.containers.get(target)
        raw_output = c.logs(
            stdout=True,
            stderr=True,
            tail=req_tail,
            timestamps=req_timestamps,
        )
        if isinstance(raw_output, bytes):
            log_str = raw_output.decode("utf-8", errors="replace")
        else:
            log_str = str(raw_output or "")

        # Truncado de seguridad para evitar saturar el contexto del LLM (ej. cuotas TPM en Groq)
        max_log_chars = 1800
        if len(log_str) > max_log_chars:
            log_str = (
                f"[Logs truncados a los últimos {max_log_chars} caracteres para no saturar cuota TPM del LLM...]\n"
                + log_str[-max_log_chars:]
            )

        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=True,
            output=log_str
            if log_str.strip()
            else "(El contenedor no ha generado líneas de log recientes)",
            duration_ms=duration,
        )
    except NotFound:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"No se encontró el contenedor Docker '{target}'.",
            duration_ms=duration,
        )
    except Exception as exc:
        duration = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            success=False,
            output="",
            error=f"Fallo al obtener logs del contenedor '{target}': {exc}",
            duration_ms=duration,
        )


class DockerLogsTool(AgentTool):
    """Herramienta para obtener los logs y registros de salida de un contenedor Docker."""

    def __init__(self, **data: Any) -> None:
        defaults: dict[str, Any] = {
            "name": "docker_logs",
            "description": (
                "Obtiene las últimas líneas de logs/stdout/stderr de un contenedor Docker específico. "
                "Permite diagnosticar fallos, excepciones, errores de arranque y estado de servicios. "
                "Parámetros: container (nombre o ID del contenedor), tail (número de líneas, defecto 100), "
                "timestamps (booleano opcional)."
            ),
            "category": "devops",
            "version": "0.1.0",
            "args_schema": DockerLogsArgs,
            "func": logs_container_fn,
            "risk_level": RiskLevel.LOW,
            "required_permissions": [],
            "tool_type": ToolType.READ,
            "read_only": True,
            "reversible": False,
            "idempotent": True,
            "makes_http_requests": False,
            "timeout_sec": 20.0,
        }
        defaults.update(data)
        super().__init__(**defaults)


def create_docker_logs_tool(**overrides: Any) -> AgentTool:
    """Factoría canónica para instanciar DockerLogsTool."""
    return DockerLogsTool(**overrides)
