# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Fachada pública y ensamblador de grafos LangGraph (StateGraph) para jg_agente.

Re-exporta la interfaz canónica asegurando compatibilidad hacia atrás con el
principio de Agnosticismo Radical del Core: la topología se ensambla exclusivamente
por introspección de capacidades sin referencias a dominios ni banderas fijas.
"""

from app.core.graph_builder import (
    GraphBuilder,
    build_agent_graph,
)
from app.core.graph_nodes import (
    default_conclude_node,
    default_evaluate_node,
    default_execute_node,
    default_human_approval_node,
    default_observe_node,
    default_plan_node,
    default_reason_node,
    default_risk_assess_node,
    default_rollback_node,
    default_verify_node,
)
from app.core.graph_routes import (
    route_after_evaluation,
    route_after_execute,
    route_after_human_approval,
    route_after_plan,
    route_after_reason,
    route_after_risk_assess,
    route_after_verify,
)
from app.core.graph_topology import GraphTopologyInfo

__all__ = [
    "GraphBuilder",
    "GraphTopologyInfo",
    "build_agent_graph",
    "default_conclude_node",
    "default_evaluate_node",
    "default_execute_node",
    "default_human_approval_node",
    "default_observe_node",
    "default_plan_node",
    "default_reason_node",
    "default_risk_assess_node",
    "default_rollback_node",
    "default_verify_node",
    "route_after_evaluation",
    "route_after_execute",
    "route_after_human_approval",
    "route_after_plan",
    "route_after_reason",
    "route_after_risk_assess",
    "route_after_verify",
]
