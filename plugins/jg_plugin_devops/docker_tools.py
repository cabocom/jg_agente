"""Herramientas de gestión y ciclo de vida de Docker para jg_plugin_devops.

Implementa DockerRestartTool bajo el contrato canónico AgentTool con nivel de riesgo
RiskLevel.HIGH, reversible=True, preservación de rollback_context y función de compensación.
"""

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
    """Obtiene el cliente de Docker activo o None si no está disponible."""
    global _custom_docker_client
    if _custom_docker_client is not None:
        return _custom_docker_client
    if docker is not None:
        try:
            return docker.from_env(timeout=5)
        except Exception as exc:
            logger.debug("Daemon de Docker no disponible vía socket local: %s", exc)
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
