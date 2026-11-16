# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Router REST para la invocación directa, síncrona y determinista de herramientas."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jg_sdk.mcp.normalizer import normalize_to_json_primitives
from pydantic import BaseModel, ConfigDict, Field

from app.security.auth import verify_control_plane_auth
from app.security.guard import SecurityGuard, get_security_guard

logger = logging.getLogger("jg_agente.api.tools")

router = APIRouter(
    prefix="/tools",
    tags=["Tools"],
    dependencies=[Depends(verify_control_plane_auth)],
)


class ToolExecutionRequest(BaseModel):
    """Petición de ejecución directa de una herramienta."""

    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Argumentos para la función"
    )
    execution_id: str | None = Field(
        default=None, description="ID opcional para correlación y auditoría"
    )
    caller_permissions: list[str] = Field(
        default_factory=list, description="Permisos del solicitante"
    )
    bypass_approval: bool = Field(
        default=False, description="Bypass explícito para ejecuciones pre-autorizadas"
    )


class ToolExecutionResponse(BaseModel):
    """Respuesta estandarizada de ejecución directa de herramienta."""

    model_config = ConfigDict(extra="allow")

    tool_name: str
    success: bool
    output: Any = Field(default="", description="Salida normalizada a primitivos JSON")
    error: str | None = Field(default=None, description="Mensaje de error si la ejecución falló")
    duration_ms: float = Field(default=0.0, description="Tiempo de ejecución en milisegundos")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadatos de auditoría y seguridad"
    )


@router.post(
    "/{tool_name}/execute",
    response_model=ToolExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Invocación directa y determinista de herramienta registrada",
    description="Ejecuta una herramienta registrada pasando por SecurityGuard sin intermediación no determinista del LLM.",
)
async def execute_tool_endpoint(
    tool_name: str,
    payload: ToolExecutionRequest,
    request: Request,
    security_guard: SecurityGuard = Depends(get_security_guard),
) -> ToolExecutionResponse:
    """Ejecuta una herramienta de forma determinista previa validación de seguridad y auditoría."""
    registry = getattr(request.app.state, "registry", None)
    tool = registry.get_tool(tool_name) if registry else None

    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Herramienta '{tool_name}' no encontrada en el registro activo.",
        )

    result = await security_guard.execute_tool(
        tool=tool,
        tool_args=payload.arguments,
        caller_permissions=payload.caller_permissions,
        bypass_approval=payload.bypass_approval,
        execution_id=payload.execution_id,
    )

    if (
        result.metadata.get("requires_approval")
        or result.metadata.get("security_decision") == "require_approval"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "La ejecución de la herramienta requiere aprobación humana previa (HITL)",
                "tool_name": tool_name,
                "risk_level": str(tool.risk_level),
                "reason": result.error,
            },
        )

    if result.metadata.get("security_decision") == "deny":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Ejecución denegada por política de seguridad",
                "tool_name": tool_name,
                "reason": result.error,
            },
        )

    return ToolExecutionResponse(
        tool_name=tool_name,
        success=result.success,
        output=normalize_to_json_primitives(result.output),
        error=result.error,
        duration_ms=result.duration_ms,
        metadata=normalize_to_json_primitives(result.metadata),
    )
