# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Definición canónica de herramientas y resultados para jg_agente.

Este módulo implementa los contratos formales AgentTool y ToolResult integrados
con el SDK desacoplado (jg_sdk.contracts), añadiendo la capacidad de adaptación
a LangChain (as_langchain_tool) requerida por el motor cognitivo.
"""

from typing import Any

from jg_sdk.contracts import (
    AgentTool as SDKAgentTool,
)
from jg_sdk.contracts import (
    RiskLevel,
    ToolResult,
    ToolType,
)
from langchain_core.tools import BaseTool, StructuredTool


class AgentTool(SDKAgentTool):
    """Contrato definitivo y descriptor de capacidades de una herramienta en jg_agente.

    Extiende el contrato canónico de jg_sdk.contracts.AgentTool integrando
    la adaptación a LangChain (as_langchain_tool) para el motor cognitivo.
    """

    def as_langchain_tool(self) -> BaseTool:
        """Convierte AgentTool en un BaseTool/StructuredTool nativo de LangChain."""

        def _wrapper(*args: Any, **kwargs: Any) -> str:
            result = self.run(*args, **kwargs)
            return str(result)

        if self.args_schema is not None:
            return StructuredTool.from_function(
                func=_wrapper,
                name=self.name,
                description=self.description,
                args_schema=self.args_schema,
            )
        return StructuredTool.from_function(
            func=_wrapper,
            name=self.name,
            description=self.description,
        )


__all__ = ["AgentTool", "RiskLevel", "ToolResult", "ToolType"]
