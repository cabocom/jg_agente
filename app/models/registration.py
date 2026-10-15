# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Modelos de contrato para registro con jg_dashboard y credenciales locales."""

from typing import Any

from pydantic import BaseModel, Field


class AgentRegistrationPayload(BaseModel):
    """Payload enviado a POST /api/v1/agents/register en jg_dashboard."""

    bootstrap_token: str = Field(..., description="Token de aprovisionamiento de 24h")
    agent_name: str | None = Field(default=None, description="Nombre asignado al agente")
    version: str | None = Field(default=None, description="Versión semántica del agente")
    capabilities: dict[str, Any] | list[dict[str, Any]] | None = Field(
        default=None, description="Catálogo de herramientas y motores"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Metadatos contextuales del agente"
    )


class AgentRegistrationResponse(BaseModel):
    """Respuesta devuelta por jg_dashboard tras consumo exitoso del bootstrap token."""

    status: str = Field(default="ACTIVE", description="Estado del agente devuelto por el Dashboard")
    message: str | None = Field(default=None, description="Mensaje informativo del Dashboard")
    agent_id: str = Field(..., description="UUID asignado al agente por el Dashboard")
    name: str = Field(..., description="Nombre registrado del agente")
    permanent_secret: str = Field(..., description="Credencial permanente generada para el agente")
    registered_at: str | None = Field(default=None, description="Timestamp ISO del registro")

    model_config = {
        "extra": "ignore",
    }


class AgentCredentials(BaseModel):
    """Credenciales persistidas en almacenamiento local seguro."""

    agent_id: str = Field(..., description="UUID del agente registrado en el Dashboard")
    permanent_secret: str = Field(..., description="Secreto permanente de autenticación")
    agent_name: str | None = Field(default=None, description="Nombre registrado del agente")
    dashboard_url: str | None = Field(default=None, description="URL del Dashboard asociado")
    registered_at: str | None = Field(
        default=None, description="Timestamp ISO en que se obtuvo la credencial"
    )
    verified: bool = Field(
        default=False,
        description="Indica si la credencial fue verificada activamente con el Dashboard",
    )

    model_config = {
        "extra": "ignore",
    }
