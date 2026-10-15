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
from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


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
    callback_url: str | None = Field(
        default=None,
        description="URL opcional de webhook HTTP para notificar la finalización de tareas asíncronas",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de generación o recepción de la solicitud",
    )


class PersistenceStatus(StrEnum):
    """Estados de persistencia para el seguimiento de almacenamiento durable."""

    PERSISTED = "persisted"
    DEGRADED = "degraded"
    FAILED = "failed"


class PersistenceMetadata(BaseModel):
    """Metadatos tipados sobre el estado de almacenamiento durable en core_executions."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: PersistenceStatus = Field(
        default=PersistenceStatus.PERSISTED,
        description="Estado de la persistencia de la ejecución",
    )
    persisted: bool = Field(
        default=True,
        description="Indica si el estado fue almacenado durablemente en base de datos",
    )
    error: str | None = Field(
        default=None,
        description="Mensaje descriptivo del error en caso de fallo o degradación",
    )
    error_type: str | None = Field(
        default=None,
        description="Tipo de excepción o código del error de persistencia",
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
    correlation_id: str | None = Field(
        default=None,
        description="Identificador único de correlación distribuida (X-Correlation-ID)",
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
    correlation_id: str | None = Field(
        default=None,
        description="Identificador único de correlación distribuida (X-Correlation-ID)",
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
    cognitive_steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Traza cronológica de saltos cognitivos por los nodos del grafo LangGraph",
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


class HITLResolutionRequest(BaseModel):
    """Payload para resolver una solicitud de intervención humana (HITL).

    Permite al operador o plano de control (Dashboard) autorizar o rechazar
    la continuación de un flujo de ejecución detenido en el nodo human_approval.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    thread_id: str | None = Field(
        default=None,
        description="Identificador del hilo (opcional si se especifica directamente en la URL)",
    )
    approver: str = Field(
        default="human_operator",
        description="Identificador o nombre del usuario/operador que resuelve la acción",
    )
    notes: str | None = Field(
        default=None,
        description="Comentarios, justificación o notas de la decisión de aprobación o rechazo",
    )
    justification: str | None = Field(
        default=None,
        description="Alias de justificación enviado por el Control Plane",
    )
    reason: str | None = Field(
        default=None,
        description="Alias de motivo de rechazo o aprobación",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos arbitrarios complementarios para auditoría",
    )

    @model_validator(mode="after")
    def populate_notes_fallback(self) -> "HITLResolutionRequest":
        if not self.notes:
            self.notes = self.justification or self.reason
        return self


class HealthComponentStatus(BaseModel):
    """Estado de un componente o subsistema individual."""

    model_config = ConfigDict(extra="allow")

    status: str = Field(
        ..., description="Estado del componente (connected, ready, disconnected, degraded)"
    )
    latency_ms: float | None = Field(
        default=None, description="Latencia observada de sondeo en milisegundos"
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Detalles adicionales o configuración"
    )
    error: str | None = Field(
        default=None, description="Error descriptivo si el componente no está saludable"
    )


class HealthResponse(BaseModel):
    """Respuesta estructurada del chequeo de salud /health."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    status: str = Field(
        default="healthy", description="Estado global del servicio (healthy, degraded, unhealthy)"
    )
    service: str = Field(default="jg_agente", description="Nombre del servicio")
    version: str = Field(..., description="Versión activa del agente")
    database: str = Field(default="unknown", description="Estado de conectividad con PostgreSQL")
    database_error: str | None = Field(default=None, description="Error de base de datos si existe")
    components: dict[str, HealthComponentStatus] = Field(
        default_factory=dict,
        description="Estado detallado por subsistema (database, llm, checkpointer)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC del chequeo de salud",
    )


class ExecutionMetrics(BaseModel):
    """Métricas cuantitativas de ejecuciones del agente."""

    model_config = ConfigDict(extra="allow")

    total_executions: int = Field(
        default=0, description="Total acumulado de ejecuciones registradas"
    )
    completed: int = Field(default=0, description="Total de ejecuciones finalizadas con éxito")
    failed: int = Field(default=0, description="Total de ejecuciones fallidas")
    cancelled: int = Field(
        default=0, description="Total de ejecuciones canceladas por rechazo HITL"
    )
    waiting_approval: int = Field(
        default=0, description="Total de ejecuciones pausadas en espera de aprobación"
    )
    in_progress: int = Field(default=0, description="Total de ejecuciones actualmente en curso")
    avg_execution_time_ms: float = Field(
        default=0.0, description="Tiempo promedio de ejecución en ms"
    )
    min_execution_time_ms: float = Field(
        default=0.0, description="Tiempo mínimo de ejecución registrado en ms"
    )
    max_execution_time_ms: float = Field(
        default=0.0, description="Tiempo máximo de ejecución registrado en ms"
    )


class MetricsResponse(BaseModel):
    """Respuesta consolidada del endpoint /metrics."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    service: str = Field(default="jg_agente", description="Nombre del servicio")
    version: str = Field(..., description="Versión activa del agente")
    uptime_seconds: float = Field(
        default=0.0, description="Segundos transcurridos desde el arranque"
    )
    executions: ExecutionMetrics = Field(
        default_factory=ExecutionMetrics,
        description="Métricas agregadas de rendimiento de ejecuciones",
    )
    capabilities: dict[str, int] = Field(
        default_factory=dict,
        description="Conteos de capacidades disponibles (tools, engines, plugins)",
    )
    hitl: dict[str, int] = Field(
        default_factory=dict,
        description="Estadísticas de gobernanza humana (approvals_requested, approvals_pending)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de generación de métricas",
    )
