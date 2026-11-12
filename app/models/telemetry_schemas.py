# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Modelos de telemetría, salud y detalle de hilos de ejecución."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ExecutionStatus


class ExecutionThreadDetail(BaseModel):
    """Detalle consolidado del estado actual, historial y checkpoints de un hilo de ejecución."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    thread_id: str = Field(
        ..., description="Identificador del hilo o sesión conversacional consultada"
    )
    execution_id: str | None = Field(
        default=None, description="Identificador de la última ejecución asociada al hilo"
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
        default=None, description="Instrucción de entrada o prompt del usuario"
    )
    response: str | None = Field(
        default=None, description="Respuesta generada o mensaje de síntesis del agente"
    )
    current_step: int = Field(default=0, description="Índice del paso actual en el grafo o plan")
    next_nodes: list[str] = Field(
        default_factory=list,
        description="Lista de nombres de nodos pendientes de ejecución en el checkpoint",
    )
    plan: dict[str, Any] | None = Field(
        default=None, description="Plan de ejecución estructurado activo si existe"
    )
    steps: list[dict[str, Any]] = Field(
        default_factory=list, description="Historial cronológico de pasos y herramientas ejecutadas"
    )
    cognitive_steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Traza cronológica de saltos cognitivos por los nodos del grafo LangGraph",
    )
    approval_status: str | None = Field(
        default=None, description="Estado de la resolución humana (pending, approved, rejected)"
    )
    requires_approval: bool = Field(
        default=False,
        description="Indica si la ejecución se encuentra pausada en espera de intervención humana (HITL)",
    )
    pending_approval_id: str | None = Field(
        default=None, description="Identificador de la acción o checkpoint pendiente de aprobación"
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
        default_factory=dict, description="Metadatos complementarios de telemetría y contexto"
    )
    created_at: datetime | None = Field(
        default=None, description="Timestamp de inicio o recepción de la ejecución"
    )
    completed_at: datetime | None = Field(
        default=None, description="Timestamp de finalización de la ejecución si ha concluido"
    )


class HITLResolutionRequest(BaseModel):
    """Payload para resolver una solicitud de intervención humana (HITL)."""

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
        default=None, description="Alias de justificación enviado por el Control Plane"
    )
    reason: str | None = Field(default=None, description="Alias de motivo de rechazo o aprobación")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadatos arbitrarios complementarios para auditoría"
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
        default_factory=lambda: datetime.now(UTC), description="Timestamp UTC del chequeo de salud"
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
