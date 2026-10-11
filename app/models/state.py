"""Estado global y modelos operacionales para el motor LangGraph de jg_agente.

Este módulo define la especificación canónica y agnóstica de AgentState,
desacoplada de dominios específicos como DevOps, infraestructura o telefonía.
El estado del entorno se representa de forma genérica mediante environment_snapshot.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field

from app.models.io import AgentInput, AgentOutput
from app.models.tools import RiskLevel

# ==========================================
# 1. Reducers para LangGraph
# ==========================================


def append_reducer(left: list[Any] | None, right: list[Any] | Sequence[Any] | None) -> list[Any]:
    """Reducer genérico para concatenar colecciones en el grafo de LangGraph."""
    return list(left or []) + list(right or [])


# ==========================================
# 2. Enums Operacionales
# ==========================================


class AgentExecutionStatus(StrEnum):
    """Estados del ciclo de vida operacional del agente."""

    IDLE = "idle"
    OBSERVING = "observing"
    REASONING = "reasoning"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    DIAGNOSING = "diagnosing"
    ROLLING_BACK = "rolling_back"
    RESOLVED = "resolved"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    """Estados de aprobación humana (HITL)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
    TIMEOUT = "timeout"


class StepStatus(StrEnum):
    """Estados de ejecución de un paso individual del plan."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


class VerificationStatus(StrEnum):
    """Estados de comprobación activa post-operación."""

    NOT_STARTED = "not_started"
    PASS = "pass"
    FAIL = "fail"
    DEGRADED = "degraded"
    SKIPPED = "skipped"


class PolicyDecision(StrEnum):
    """Decisiones del motor de políticas de seguridad."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HUMAN_APPROVAL = "require_human_approval"


class GoalStatus(StrEnum):
    """Estados semánticos de resolución del objetivo tras un ciclo de ejecución."""

    SATISFIED = "satisfied"
    NEEDS_MORE_INFO = "needs_more_info"
    BLOCKED_MISSING_CAPABILITY = "blocked_missing_capability"
    FAILED = "failed"


# ==========================================
# 3. Modelos Estructurados Agnosticos
# ==========================================


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
        default_factory=list,
        description="Lista de step_ids previos requeridos antes de este paso",
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
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp de solicitud",
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
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC de la evaluación",
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
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp de ejecución",
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
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC del evento",
    )


class ExecutionError(BaseModel):
    """Error operacional capturado durante el ciclo del agente."""

    model_config = ConfigDict(extra="allow")

    code: str = Field(..., description="Código de clasificación del error")
    message: str = Field(..., description="Mensaje explicativo del fallo")
    component: str = Field(..., description="Componente o nodo de origen")
    fatal: bool = Field(default=False, description="Indica si detiene el flujo por completo")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp del error",
    )


class CognitiveStepRecord(BaseModel):
    """Registro de salto cognitivo o transición de nodo dentro del grafo LangGraph."""

    model_config = ConfigDict(extra="allow")

    step_id: str = Field(..., description="Identificador único del salto cognitivo")
    node: str = Field(
        ...,
        description="Identificador del nodo (reason, security_eval, execute, conclude, etc.)",
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
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp UTC del paso cognitivo",
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
        default_factory=lambda: datetime.now(UTC),
        description="Marca temporal UTC de la evaluación",
    )


# ==========================================
# 4. AgentState (TypedDict para LangGraph)
# ==========================================


class AgentState(TypedDict, total=False):
    """Estado global agnóstico del grafo de ejecución para LangGraph.

    No contiene referencias a infraestructura, contenedores ni tecnologías específicas.
    La información del entorno se modela mediante el diccionario genérico environment_snapshot,
    permitiendo a cada plugin almacenar sus datos de dominio sin contaminar el Core.
    """

    # 1. Petición y Estímulo
    request: AgentInput
    correlation_id: str | None
    caller_permissions: list[str] | None

    # 2. Historial conversacional y mensajería
    messages: Annotated[list[BaseMessage], add_messages]

    # 3. Comprensión y Observación del Entorno
    intent: IntentModel | dict[str, Any] | None
    environment_snapshot: dict[str, Any] | None

    # 4. Planificación y Evaluación de Riesgo
    plan: ExecutionPlan | dict[str, Any] | None
    risk_assessment: dict[str, Any] | None

    # 5. Aprobación Humana (HITL)
    approval: ApprovalRecord | dict[str, Any] | None
    requires_approval: bool
    approved_step_ids: list[str] | None
    approved_tool_names: list[str] | None

    # 6. Trazas de Ejecución, Rollback y Verificación
    execution_records: Annotated[list[StepExecutionRecord], append_reducer]
    cognitive_steps: Annotated[list[CognitiveStepRecord], append_reducer]
    verification_results: Annotated[list[dict[str, Any]], append_reducer]

    rollback_records: Annotated[list[dict[str, Any]], append_reducer]
    requires_rollback: bool
    diagnostic_report: dict[str, Any] | str | None

    # 7. Control de Flujo y Ciclos de Razonamiento
    iteration: int
    max_iterations: int
    evaluation_records: Annotated[list[EvaluationRecord], append_reducer]

    status: AgentExecutionStatus | str
    current_step: int
    retry_count: int
    circuit_breaker_active: bool
    checkpoint_degraded: bool
    human_intervention_required: bool
    is_resolved: bool
    stop_reason: str | None

    # 8. Errores y Auditoría Inmutable
    errors: Annotated[list[ExecutionError], append_reducer]
    audit_trail: Annotated[list[AuditRecord], append_reducer]

    # 9. Salida Sintetizada Normalizada
    output: AgentOutput | dict[str, Any] | None


def resolve_caller_permissions(state: AgentState | dict[str, Any]) -> list[str]:
    """Resuelve los permisos del llamador de forma determinista y jerárquica a partir del estado.

    Garantiza la trazabilidad inmutable de caller_permissions a lo largo de todo el grafo
    cognitivo, evitando denegaciones falsas por INSUFFICIENT_PERMISSIONS (AGENTE-LOGIC-03).
    """
    state_perms = state.get("caller_permissions")
    if state_perms is not None:
        return list(state_perms)

    req = state.get("request")
    if req is not None:
        user_context = getattr(req, "user_context", None)
        if user_context is not None:
            perms_list = (
                list(user_context.permissions) if getattr(user_context, "permissions", None) else []
            )
            metadata = getattr(req, "metadata", None)
            is_admin = getattr(user_context, "role", None) == "admin" or (
                isinstance(metadata, dict) and metadata.get("user_role") == "admin"
            )
            if is_admin:
                return list(set(perms_list + ["role:admin", "admin", "*"]))
            return perms_list

        metadata = getattr(req, "metadata", None)
        if isinstance(metadata, dict) and "caller_permissions" in metadata:
            raw = metadata.get("caller_permissions")
            if isinstance(raw, list):
                return [str(p) for p in raw]

    return []
