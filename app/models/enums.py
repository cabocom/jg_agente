# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Enumeraciones canónicas y estados operacionales para jg_agente."""

from enum import StrEnum


class ExecutionStatus(StrEnum):
    """Estados posibles de una ejecución del agente."""

    COMPLETED = "completed"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"
    TIMEOUT = "timeout"


class PersistenceStatus(StrEnum):
    """Estados de persistencia para el seguimiento de almacenamiento durable."""

    PERSISTED = "persisted"
    DEGRADED = "degraded"
    FAILED = "failed"


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
