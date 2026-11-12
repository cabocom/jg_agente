# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Estado global y modelos operacionales para el motor LangGraph de jg_agente.

Este módulo define la especificación canónica y agnóstica de AgentState,
desacoplada de dominios específicos como DevOps, infraestructura o telefonía.
El estado del entorno se representa de forma genérica mediante environment_snapshot.
"""

from collections.abc import Sequence
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.models.enums import (
    AgentExecutionStatus,
    ApprovalStatus,
    GoalStatus,
    PolicyDecision,
    StepStatus,
    VerificationStatus,
)
from app.models.io import AgentInput, AgentOutput
from app.models.records import (
    ApprovalRecord,
    AuditRecord,
    CognitiveStepRecord,
    EvaluationRecord,
    ExecutionError,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    SecurityEvaluationResult,
    StepExecutionRecord,
)

__all__ = [
    "append_reducer",
    "AgentExecutionStatus",
    "ApprovalStatus",
    "StepStatus",
    "VerificationStatus",
    "PolicyDecision",
    "GoalStatus",
    "IntentModel",
    "PlanStep",
    "ExecutionPlan",
    "ApprovalRecord",
    "SecurityEvaluationResult",
    "StepExecutionRecord",
    "AuditRecord",
    "ExecutionError",
    "CognitiveStepRecord",
    "EvaluationRecord",
    "AgentState",
    "resolve_caller_permissions",
]


def append_reducer(left: list[Any] | None, right: list[Any] | Sequence[Any] | None) -> list[Any]:
    """Reducer genérico para concatenar colecciones en el grafo de LangGraph."""
    return list(left or []) + list(right or [])


class AgentState(TypedDict, total=False):
    """Estado global agnóstico del grafo de ejecución para LangGraph."""

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
    """Resuelve los permisos del llamador de forma determinista y jerárquica a partir del estado."""
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
