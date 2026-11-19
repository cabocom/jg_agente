# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Modelos de entrada y salida desacoplados para jg_agente.

Re-exporta los contratos canónicos AgentInput, AgentOutput, UserContext
y PersistenceMetadata desde jg_sdk, garantizando interoperabilidad y DRY.
"""

from jg_sdk import (
    AgentInput,
    AgentOutput,
    PersistenceMetadata,
    UserContext,
)

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
    "AgentInput",
    "AgentOutput",
    "ExecutionMetrics",
    "ExecutionStatus",
    "ExecutionThreadDetail",
    "HITLResolutionRequest",
    "HealthComponentStatus",
    "HealthResponse",
    "MetricsResponse",
    "PersistenceMetadata",
    "PersistenceStatus",
    "UserContext",
]
