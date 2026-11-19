# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Enumeraciones canónicas y estados operacionales para jg_agente.

Re-exporta enums canónicos desde jg_sdk garantizando DRY y define estados
específicos del runtime LangGraph de jg_agente.
"""

from enum import StrEnum

from jg_sdk import (
    ApprovalStatus,
    ExecutionStatus,
    GoalStatus,
    PersistenceStatus,
    PolicyDecision,
    RiskLevel,
    StepStatus,
    ToolType,
    VerificationStatus,
)


class AgentExecutionStatus(StrEnum):
    """Estados del ciclo de vida operacional del agente en LangGraph."""

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


__all__ = [
    "AgentExecutionStatus",
    "ApprovalStatus",
    "ExecutionStatus",
    "GoalStatus",
    "PersistenceStatus",
    "PolicyDecision",
    "RiskLevel",
    "StepStatus",
    "ToolType",
    "VerificationStatus",
]
