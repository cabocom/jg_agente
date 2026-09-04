"""Módulo de modelos y contratos del Core de jg_agente."""

from app.models.io import (
    AgentInput,
    AgentOutput,
    ExecutionStatus,
    UserContext,
)
from app.models.state import (
    AgentExecutionStatus,
    AgentState,
    ApprovalRecord,
    ApprovalStatus,
    AuditRecord,
    ExecutionError,
    ExecutionPlan,
    IntentModel,
    PlanStep,
    PolicyDecision,
    SecurityEvaluationResult,
    StepExecutionRecord,
    StepStatus,
    VerificationStatus,
    append_reducer,
)
from app.models.tools import (
    AgentTool,
    RiskLevel,
    ToolResult,
    ToolType,
)

__all__ = [
    "AgentExecutionStatus",
    "AgentInput",
    "AgentOutput",
    "AgentState",
    "AgentTool",
    "ApprovalRecord",
    "ApprovalStatus",
    "AuditRecord",
    "ExecutionError",
    "ExecutionPlan",
    "ExecutionStatus",
    "IntentModel",
    "PlanStep",
    "PolicyDecision",
    "RiskLevel",
    "SecurityEvaluationResult",
    "StepExecutionRecord",
    "StepStatus",
    "ToolResult",
    "ToolType",
    "UserContext",
    "VerificationStatus",
    "append_reducer",
]
