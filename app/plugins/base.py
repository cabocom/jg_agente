# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Contratos base, metadatos y ciclo de vida del sistema de plugins de jg_agente.

Re-exporta los contratos canónicos desde jg_sdk.contracts_plugins garantizando
compatibilidad hacia atrás y principio DRY estricto.
"""

from jg_sdk.contracts_plugins import (
    BaseEngine,
    BasePlugin,
    ObserverEngine,
    PlannerEngine,
    PluginMetadata,
    VerifierEngine,
)

__all__ = [
    "BaseEngine",
    "BasePlugin",
    "ObserverEngine",
    "PlannerEngine",
    "PluginMetadata",
    "VerifierEngine",
]
