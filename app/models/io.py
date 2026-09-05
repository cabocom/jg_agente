"""Modelos de entrada y salida desacoplados para jg_agente.

Este módulo define los contratos formales para interactuar con el motor
cognitivo del Execution Plane (AgentInput y AgentOutput), garantizando
agnosticismo respecto a protocolos y canales de transporte externos.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ExecutionStatus(StrEnum):
    """Estados posibles de una ejecución del agente."""

    COMPLETED = "completed"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"
    TIMEOUT = "timeout"


class UserContext(BaseModel):
    """Contexto estructurado del usuario o entidad que solicita la ejecución.

    Permite propagar información de identidad y permisos desde el plano de control
    (Dashboard) o gateways de autenticación hacia el SecurityGuard del agente.
    """

    model_config = ConfigDict(extra="allow")

    user_id: str | None = Field(
        default=None, description="Identificador único del usuario solicitante"
    )
    username: str | None = Field(
        default=None, description="Nombre de usuario o identificador visual"
    )
    email: str | None = Field(default=None, description="Correo electrónico del usuario")
    role: str | None = Field(
        default=None, description="Rol RBAC del usuario (ej. admin, operator, viewer)"
    )
    permissions: list[str] = Field(
        default_factory=list,
        description="Lista de permisos o scopes concedidos al usuario",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos contextuales adicionales del usuario",
    )


class AgentInput(BaseModel):
    """Contrato formal de entrada para el ciclo cognitivo del agente.

    Representa un estímulo normalizado. El agente desconoce por completo
    si la solicitud se originó en una llamada telefónica, un bot de mensajería,
    un webhook o una llamada a la API REST.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    execution_id: str = Field(
        ...,
        description="Identificador único de la ejecución asignado por el invocador",
    )
    thread_id: str = Field(
        ...,
        validation_alias=AliasChoices("thread_id", "session_id"),
        description="Identificador de la sesión o hilo conversacional persistente",
    )
    prompt: str = Field(
        ...,
        validation_alias=AliasChoices("prompt", "message"),
        description="Texto o instrucción principal normalizada para el agente",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parámetros opcionales parametrizados de la invocación",
    )
    user_context: UserContext | None = Field(
        default=None,
        description="Contexto opcional de identidad y permisos del usuario",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos arbitrarios complementarios de la solicitud",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de generación o recepción de la solicitud",
    )


class AgentOutput(BaseModel):
    """Contrato formal de salida emitido por el ciclo cognitivo del agente.

    Representa la respuesta sintetizada del agente una vez concluido el ciclo
    o pausado en espera de intervención humana (HITL).
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    execution_id: str = Field(
        ...,
        description="Identificador único de la ejecución a la que corresponde la salida",
    )
    thread_id: str = Field(
        ...,
        validation_alias=AliasChoices("thread_id", "session_id"),
        description="Identificador de la sesión o hilo conversacional asociado",
    )
    status: ExecutionStatus = Field(
        default=ExecutionStatus.COMPLETED,
        description="Estado final o actual de la ejecución",
    )
    response: str = Field(
        ...,
        validation_alias=AliasChoices("response", "answer"),
        description="Respuesta textual final o mensaje generado por el agente",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Carga de datos estructurados o artefactos producidos",
    )
    execution_time_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Duración total de la ejecución en milisegundos",
    )
    requires_approval: bool = Field(
        default=False,
        description="Flag que indica si la ejecución se detuvo requiriendo aprobación humana (HITL)",
    )
    pending_approval_id: str | None = Field(
        default=None,
        description="Identificador de la acción pendiente que requiere confirmación",
    )
    error: str | None = Field(
        default=None,
        description="Mensaje descriptivo del error en caso de que status sea FAILED",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos adicionales de auditoría o ejecución",
    )
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de conclusión o emisión del resultado",
    )


class ExecutionThreadDetail(BaseModel):
    """Detalle consolidado del estado actual, historial y checkpoints de un hilo de ejecución.

    Permite al plano de control (Dashboard) o clientes autorizados inspeccionar
    el progreso, pasos ejecutados, evaluación de riesgos, pausas HITL y diagnósticos.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    thread_id: str = Field(
        ...,
        description="Identificador del hilo o sesión conversacional consultada",
    )
    execution_id: str | None = Field(
        default=None,
        description="Identificador de la última ejecución asociada al hilo",
    )
    status: ExecutionStatus | str = Field(
        default=ExecutionStatus.IN_PROGRESS,
        description="Estado operacional o final de la ejecución",
    )
    prompt: str | None = Field(
        default=None,
        description="Instrucción de entrada o prompt del usuario",
    )
    response: str | None = Field(
        default=None,
        description="Respuesta generada o mensaje de síntesis del agente",
    )
    current_step: int = Field(
        default=0,
        description="Índice del paso actual en el grafo o plan",
    )
    next_nodes: list[str] = Field(
        default_factory=list,
        description="Lista de nombres de nodos pendientes de ejecución en el checkpoint",
    )
    plan: dict[str, Any] | None = Field(
        default=None,
        description="Plan de ejecución estructurado activo si existe",
    )
    steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Historial cronológico de pasos y herramientas ejecutadas",
    )
    approval_status: str | None = Field(
        default=None,
        description="Estado de la resolución humana (pending, approved, rejected)",
    )
    requires_approval: bool = Field(
        default=False,
        description="Indica si la ejecución se encuentra pausada en espera de intervención humana (HITL)",
    )
    pending_approval_id: str | None = Field(
        default=None,
        description="Identificador de la acción o checkpoint pendiente de aprobación",
    )
    errors: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de errores operacionales capturados durante el ciclo",
    )
    checkpoint_id: str | None = Field(
        default=None,
        description="Identificador del checkpoint persistente activo en el checkpointer",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos complementarios de telemetría y contexto",
    )
    created_at: datetime | None = Field(
        default=None,
        description="Timestamp de inicio o recepción de la ejecución",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Timestamp de finalización de la ejecución si ha concluido",
    )
