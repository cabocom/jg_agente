# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Nodos canónicos y wrappers de delegación por defecto para el grafo LangGraph."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.registry import CapabilityRegistry
from app.models.state import AgentState
from app.security.guard import SecurityGuard


async def default_observe_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de observación: captura el estado del entorno delegando en observe_node."""
    from app.nodes.observe import observe_node

    return await observe_node(state, registry=registry)


async def default_reason_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Nodo de razonamiento cognitivo: delega en el nodo reason con modelo LLM configurable."""
    from app.nodes.reason import reason_node

    return await reason_node(state, registry, llm=llm)


async def default_plan_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de planificación: genera una secuencia de pasos estructurados delegando en plan_node."""
    from app.nodes.plan import plan_node

    return await plan_node(state, registry=registry)


async def default_risk_assess_node(
    state: AgentState,
    registry: CapabilityRegistry,
    security_guard: SecurityGuard,
) -> dict[str, Any]:
    """Nodo de evaluación de riesgo de operaciones delegando en risk_assess_node."""
    from app.nodes.risk_assess import risk_assess_node

    return await risk_assess_node(state, registry=registry, security_guard=security_guard)


async def default_human_approval_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de gestión de aprobación humana (HITL) delegando en human_approval_node."""
    from app.nodes.human_approval import human_approval_node

    return await human_approval_node(state, registry=registry)


async def default_execute_node(
    state: AgentState,
    registry: CapabilityRegistry,
    security_guard: SecurityGuard,
) -> dict[str, Any]:
    """Nodo de ejecución de acciones: delega en execute_node bajo sandbox seguro."""
    from app.nodes.execute import execute_node

    return await execute_node(state, registry, security_guard=security_guard)


async def default_verify_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de verificación: delega en verify_node."""
    from app.nodes.verify import verify_node

    return await verify_node(state, registry=registry)


async def default_rollback_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de compensación (Rollback): delega en rollback_node."""
    from app.nodes.rollback import rollback_node

    return await rollback_node(state, registry=registry)


async def default_evaluate_node(
    state: AgentState,
    registry: CapabilityRegistry,
    llm: BaseChatModel | None = None,
) -> dict[str, Any]:
    """Nodo de evaluación semántica: delega en evaluate_node con capability-awareness."""
    from app.nodes.evaluate import evaluate_node

    return await evaluate_node(state, registry=registry, llm=llm)


async def default_conclude_node(
    state: AgentState,
    registry: CapabilityRegistry,
) -> dict[str, Any]:
    """Nodo de conclusión: delega en conclude_node para consolidar la salida AgentOutput."""
    from app.nodes.conclude import conclude_node

    return await conclude_node(state, registry=registry)
