# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Modelos de introspección de topología para grafos LangGraph."""

from pydantic import BaseModel, Field


class GraphTopologyInfo(BaseModel):
    """Metadatos de la topología del grafo ensamblado dinámicamente."""

    nodes: list[str] = Field(
        default_factory=list,
        description="Identificadores de todos los nodos agregados al grafo",
    )
    conditional_nodes: list[str] = Field(
        default_factory=list,
        description="Nodos condicionales incluidos basados en capacidades registradas",
    )
    has_observer: bool = Field(default=False, description="Indica si se conectó el nodo observe")
    has_planner: bool = Field(default=False, description="Indica si se conectó el nodo plan")
    has_risk_assessment: bool = Field(
        default=False, description="Indica si se conectó el nodo risk_assess"
    )
    has_human_approval: bool = Field(
        default=False, description="Indica si se conectó el nodo human_approval"
    )
    has_verifier: bool = Field(default=False, description="Indica si se conectó el nodo verify")
    has_rollback: bool = Field(default=False, description="Indica si se conectó el nodo rollback")
    has_evaluator: bool = Field(default=True, description="Indica si se conectó el nodo evaluate")
