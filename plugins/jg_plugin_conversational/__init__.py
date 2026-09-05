"""Paquete jg_plugin_conversational para jg_agente.

Provee capacidades de diálogo e interacción conversacional cumpliendo el
contrato formal BasePlugin del Execution Plane.
"""

from jg_plugin_conversational.plugin import ConversationalPlugin

PLUGIN_CLASS = ConversationalPlugin
__version__ = "0.1.0"

__all__ = ["ConversationalPlugin", "PLUGIN_CLASS", "__version__"]
