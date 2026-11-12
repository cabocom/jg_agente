# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Modelos estructurados de trazabilidad, ejecución y auditoría para el ciclo cognitivo."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApprovalStatus, GoalStatus, PolicyDecision, StepStatus
from app.models.tools import RiskLevel


class IntentModel(BaseModel):
    """Intención procesada a partir de un estímulo de entrada."""

    model_config = ConfigDict(extra="allow")

    goal: str = Field(..., description="Objetivo principal formulado para el agente")
    action_type: str = Field(default="general", description="Categoría de acción a ejecutar")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Parámetros extraídos")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Nivel de certidumbre")
    reasoning: str | None = Field(default=None, description="Justificación cognitiva del LLM")


class PlanStep(BaseModel):
    """Paso unitario dentro de un plan de ejecución."""

    model_config = ConfigDict(extra="allow")

    step_id: str = Field(..., description="Identificador único del paso")
    tool_name: str = Field(..., description="Nombre de la herramienta a invocar")
    tool_args: dict[str, Any] = Field(
        default_factory=dict, description="Argumentos para la herramienta"
    )
    description: str = Field(default="", description="Descripción legible del paso")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="Nivel de riesgo del paso")
    reversible: bool = Field(default=False, description="Indica si el paso es compensable")
    allow_failure: bool = Field(
        default=False,
        description="Indica si un fallo en este paso es no fatal y permite continuar con la ejecución del resto del plan",
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Lista de step_ids previos requeridos antes de este paso"
    )
    status: StepStatus = Field(default=StepStatus.PENDING, description="Estado del paso")


class ExecutionPlan(BaseModel):
    """Plan de ejecución estructurado compuesto por pasos ordenados."""

    model_config = ConfigDict(extra="allow")

    plan_id: str = Field(..., description="Identificador único del plan")
    goal: str = Field(..., description="Objetivo general que persigue el plan")
    steps: list[PlanStep] = Field(default_factory=list, description="Secuencia ordenada de pasos")
    estimated_risk: RiskLevel = Field(default=RiskLevel.LOW, description="Riesgo máximo estimado")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de formulación del plan",
    )


class ApprovalRecord(BaseModel):
    """Registro de autorización humana para operaciones de riesgo (HITL)."""

    model_config = ConfigDict(extra="allow")

    status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING, description="Estado de la aprobación"
    )
    approver: str | None = Field(default=None, description="Identificador o usuario que autorizó")
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp de solicitud"
    )
    decided_at: datetime | None = Field(default=None, description="Timestamp de decisión")
    notes: str | None = Field(default=None, description="Comentarios u observaciones")
    rejection_reason: str | None = Field(default=None, description="Motivo de rechazo")
    approved_step_ids: list[str] = Field(
        default_factory=list,
        description="Lista de identificadores de pasos explícitamente aprobados",
    )
    approved_tool_names: list[str] = Field(
        default_factory=list,
        description="Lista de nombres de herramientas explícitamente aprobadas",
    )


class SecurityEvaluationResult(BaseModel):
    """Resultado formal de la evaluación de seguridad antes de ejecutar una operación."""

    model_config = ConfigDict(extra="allow")

    decision: PolicyDecision = Field(
        default=PolicyDecision.ALLOW, description="Decisión de política de seguridad"
    )
    operation: str = Field(default="", description="Nombre de la operación o herramienta evaluada")
    target_resource: str = Field(default="", description="Recurso o parámetro objetivo evaluado")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="Nivel de riesgo determinado")
    reason: str = Field(default="", description="Motivo o justificación de la decisión")
    required_permissions: list[str] = Field(
        default_factory=list, description="Permisos necesarios para la ejecución"
    )
    is_reversible: bool = Field(default=True, description="Indica si la acción es compensable")
    can_cause_data_loss: bool = Field(
        default=False, description="Indica si la acción puede ocasionar pérdida de datos"
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp UTC de la evaluación"
    )


class StepExecutionRecord(BaseModel):
    """Traza auditable de ejecución de un paso o herramienta."""

    model_config = ConfigDict(extra="allow")

    step_id: str = Field(..., description="Identificador del paso correspondiente")
    tool_name: str = Field(..., description="Herramienta ejecutada")
    tool_args: dict[str, Any] = Field(default_factory=dict, description="Argumentos suministrados")
    status: StepStatus = Field(
        default=StepStatus.COMPLETED, description="Resultado de la ejecución"
    )
    output: Any = Field(default="", description="Salida producida por la herramienta")
    error: str | None = Field(default=None, description="Mensaje de error si falló")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Duración en milisegundos")
    rollback_context: dict[str, Any] | None = Field(
        default=None, description="Contexto de compensación"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp de ejecución"
    )


class AuditRecord(BaseModel):
    """Registro inmutable de auditoría para compliance y observabilidad."""

    model_config = ConfigDict(extra="allow")

    event_type: str = Field(..., description="Tipo de evento registrado")
    actor: str = Field(default="agent", description="Entidad o componente emisor")
    details: dict[str, Any] = Field(default_factory=dict, description="Detalles del evento")
    correlation_id: str | None = Field(
        default=None,
        description="Identificador único de correlación distribuida (X-Correlation-ID)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp UTC del evento"
    )


class ExecutionError(BaseModel):
    """Error operacional capturado durante el ciclo del agente."""

    model_config = ConfigDict(extra="allow")

    code: str = Field(..., description="Código de clasificación del error")
    message: str = Field(..., description="Mensaje explicativo del fallo")
    component: str = Field(..., description="Componente o nodo de origen")
    fatal: bool = Field(default=False, description="Indica si detiene el flujo por completo")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp del error"
    )


class CognitiveStepRecord(BaseModel):
    """Registro de salto cognitivo o transición de nodo dentro del grafo LangGraph."""

    model_config = ConfigDict(extra="allow")

    step_id: str = Field(..., description="Identificador único del salto cognitivo")
    node: str = Field(
        ..., description="Identificador del nodo (reason, security_eval, execute, conclude, etc.)"
    )
    title: str = Field(default="", description="Título descriptivo y legible del salto")
    action: str = Field(default="", description="Acción o propósito específico del salto")
    description: str = Field(
        default="", description="Descripción detallada de la decisión o resultado cognitivo"
    )
    status: str = Field(
        default="completed",
        description="Estado del paso (completed, failed, waiting_approval, skipped)",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Datos y metadatos complementarios (args, riesgo, razonamiento)",
    )
    duration_ms: float = Field(default=0.0, ge=0.0, description="Duración del nodo en milisegundos")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp UTC del paso cognitivo"
    )


class EvaluationRecord(BaseModel):
    """Registro estructurado de la evaluación semántica post-ejecución."""

    model_config = ConfigDict(extra="allow")

    iteration: int = Field(default=1, ge=1, description="Número de iteración del ciclo cognitivo")
    goal_status: GoalStatus = Field(
        ..., description="Estado de satisfacción del objetivo del usuario"
    )
    explanation: str = Field(
        ..., description="Síntesis semántica y justificación de la decisión por el LLM"
    )
    missing_capabilities: list[str] = Field(
        default_factory=list,
        description="Capacidades o herramientas necesarias detectadas como ausentes",
    )
    suggested_next_action: str | None = Field(
        default=None, description="Acción o herramienta recomendada para la siguiente iteración"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Marca temporal UTC de la evaluación"
    )
