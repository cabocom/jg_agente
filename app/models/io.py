# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Modelos de entrada y salida desacoplados para jg_agente.

Este módulo define los contratos formales para interactuar con el motor
cognitivo del Execution Plane (AgentInput y AgentOutput), garantizando
agnosticismo respecto a protocolos y canales de transporte externos.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.models.enums import ExecutionStatus, PersistenceStatus
from app.models.telemetry_schemas import (
    ExecutionMetrics,
    ExecutionThreadDetail,
    HealthComponentStatus,
    HealthResponse,
    HITLResolutionRequest,
    MetricsResponse,
)

__all__ = [
    "ExecutionStatus",
    "PersistenceStatus",
    "UserContext",
    "AgentInput",
    "PersistenceMetadata",
    "AgentOutput",
    "ExecutionThreadDetail",
    "HITLResolutionRequest",
    "HealthComponentStatus",
    "HealthResponse",
    "ExecutionMetrics",
    "MetricsResponse",
]


class UserContext(BaseModel):
    """Contexto estructurado del usuario o entidad que solicita la ejecución."""

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
        default_factory=list, description="Lista de permisos o scopes concedidos al usuario"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadatos contextuales adicionales del usuario"
    )


class AgentInput(BaseModel):
    """Contrato formal de entrada para el ciclo cognitivo del agente."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    execution_id: str = Field(
        ..., description="Identificador único de la ejecución asignado por el invocador"
    )
    thread_id: str = Field(
        ...,
        validation_alias=AliasChoices("thread_id", "session_id"),
        description="Identificador de la sesión o hilo conversacional persistente",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Identificador único de correlación distribuida (X-Correlation-ID)",
    )
    prompt: str = Field(
        ...,
        validation_alias=AliasChoices("prompt", "message"),
        description="Texto o instrucción principal normalizada para el agente",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Parámetros opcionales parametrizados de la invocación"
    )
    user_context: UserContext | None = Field(
        default=None, description="Contexto opcional de identidad y permisos del usuario"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadatos arbitrarios complementarios de la solicitud"
    )
    locale: str = Field(
        default="es", description="Código de idioma de la ejecución ('es', 'en', 'fr', 'de', 'it')"
    )
    callback_url: str | None = Field(
        default=None,
        description="URL opcional de webhook HTTP para notificar la finalización de tareas asíncronas",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de generación o recepción de la solicitud",
    )


class PersistenceMetadata(BaseModel):
    """Metadatos tipados sobre el estado de almacenamiento durable en core_executions."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: PersistenceStatus = Field(
        default=PersistenceStatus.PERSISTED, description="Estado de la persistencia de la ejecución"
    )
    persisted: bool = Field(
        default=True, description="Indica si el estado fue almacenado durablemente en base de datos"
    )
    error: str | None = Field(
        default=None, description="Mensaje descriptivo del error en caso de fallo o degradación"
    )
    error_type: str | None = Field(
        default=None, description="Tipo de excepción o código del error de persistencia"
    )


class AgentOutput(BaseModel):
    """Contrato formal de salida emitido por el ciclo cognitivo del agente."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    execution_id: str = Field(
        ..., description="Identificador único de la ejecución a la que corresponde la salida"
    )
    thread_id: str = Field(
        ...,
        validation_alias=AliasChoices("thread_id", "session_id"),
        description="Identificador de la sesión o hilo conversacional asociado",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Identificador único de correlación distribuida (X-Correlation-ID)",
    )
    status: ExecutionStatus = Field(
        default=ExecutionStatus.COMPLETED, description="Estado final o actual de la ejecución"
    )
    response: str = Field(
        ...,
        validation_alias=AliasChoices("response", "answer"),
        description="Respuesta textual final o mensaje generado por el agente",
    )
    data: dict[str, Any] | None = Field(
        default=None, description="Carga de datos estructurados o artefactos producidos"
    )
    execution_time_ms: float = Field(
        default=0.0, ge=0.0, description="Duración total de la ejecución en milisegundos"
    )
    requires_approval: bool = Field(
        default=False,
        description="Flag que indica si la ejecución se detuvo requiriendo aprobación humana (HITL)",
    )
    pending_approval_id: str | None = Field(
        default=None, description="Identificador de la acción pendiente que requiere confirmación"
    )
    error: str | None = Field(
        default=None, description="Mensaje descriptivo del error en caso de que status sea FAILED"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadatos adicionales de auditoría o ejecución"
    )
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de conclusión o emisión del resultado",
    )
