# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Servicios de dominio y orquestación del motor cognitivo de jg_agente."""

from app.services.background_execution_service import (
    run_in_background,
)
from app.services.execution_notification_service import (
    get_agent_credentials,
    notify_execution_completion,
)
from app.services.execution_orchestrator import (
    execute_graph_pipeline,
    get_agent_graph,
)
from app.services.execution_persistence_service import (
    persist_or_update_execution,
    persist_with_retry,
    spool_emergency_execution,
)
from app.services.execution_query_service import (
    get_execution_thread_detail,
)
from app.services.hitl_interrupt_service import (
    handle_hitl_interrupt,
)
from app.services.hitl_resume_service import (
    resolve_hitl_execution,
)

__all__ = [
    "execute_graph_pipeline",
    "get_agent_credentials",
    "get_agent_graph",
    "get_execution_thread_detail",
    "handle_hitl_interrupt",
    "notify_execution_completion",
    "persist_or_update_execution",
    "persist_with_retry",
    "resolve_hitl_execution",
    "run_in_background",
    "spool_emergency_execution",
]
