# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Modelos estructurados de trazabilidad, ejecución y auditoría para el ciclo cognitivo.

Re-exporta contratos canónicos desde jg_sdk y define modelos específicos
del runtime LangGraph de jg_agente.
"""

from datetime import UTC, datetime
from typing import Any

from jg_sdk import (
    ApprovalRecord,
    AuditRecord,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    SecurityEvaluationResult,
    StepExecutionRecord,
)
from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import GoalStatus


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


__all__ = [
    "ApprovalRecord",
    "AuditRecord",
    "CognitiveStepRecord",
    "EvaluationRecord",
    "ExecutionError",
    "ExecutionPlan",
    "IntentModel",
    "PlanStep",
    "SecurityEvaluationResult",
    "StepExecutionRecord",
]
