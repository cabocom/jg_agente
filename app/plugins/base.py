# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Contratos base, metadatos y ciclo de vida del sistema de plugins de jg_agente."""

import re
from abc import ABC, abstractmethod
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.tools import AgentTool


class PluginMetadata(BaseModel):
    """Metadatos descriptivos y requerimientos de compatibilidad del plugin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Identificador único del plugin (slug alfanumérico en minúsculas con guiones o guiones bajos).",
    )
    version: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Versión del plugin siguiendo Versionado Semántico (e.g. '1.0.0').",
    )
    description: str = Field(
        default="",
        max_length=512,
        description="Descripción legible del propósito y dominio del plugin.",
    )
    author: str = Field(
        default="",
        max_length=128,
        description="Autor u organización responsable del plugin.",
    )
    jg_agente_version_min: str = Field(
        default="1.0.0",
        description="Versión mínima del Core de jg_agente requerida para compatibilidad.",
    )
    enabled: bool = Field(
        default=True,
        description="Indica si el plugin se encuentra activo y listo para ser utilizado.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Etiquetas clasificatorias del plugin (e.g. ['network', 'devops']).",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Nombres de otros plugins requeridos por este plugin.",
    )
    config_schema: type[BaseModel] | None = Field(
        default=None,
        description="Esquema Pydantic opcional para validar la configuración/env vars del plugin.",
    )
    supported_locales: list[str] = Field(
        default_factory=lambda: ["es", "en", "fr", "de", "it"],
        description="Lista de códigos de idioma soportados por el plugin.",
    )
    default_locale: str | None = Field(
        default=None,
        description="Idioma preferido declarado por el plugin ('es', 'en', 'fr', 'de', 'it').",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos o configuraciones adicionales no estructuradas.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Valida que el identificador del plugin sea un slug normalizado."""
        clean = v.strip().lower()
        if not clean:
            raise ValueError("El nombre del plugin no puede estar vacío.")
        if not re.match(r"^[a-z0-9_-]+$", clean):
            raise ValueError(
                f"El nombre del plugin '{v}' debe contener únicamente caracteres alfanuméricos, guiones o guiones bajos."
            )
        return clean


class BaseEngine(ABC):
    """Contrato base para motores de dominio cognitivos o de infraestructura."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre identificador único del motor."""
        ...

    @property
    @abstractmethod
    def engine_type(self) -> str:
        """Tipo o rol del motor (e.g. 'observer', 'planner', 'verifier', 'discovery', 'custom')."""
        ...

    async def startup(self) -> None:  # noqa: B027
        """Hook opcional de inicio del motor para adquirir recursos o conexiones."""
        pass

    async def shutdown(self) -> None:  # noqa: B027
        """Hook opcional de finalización del motor para liberar recursos o conexiones."""
        pass


class ObserverEngine(BaseEngine, ABC):
    """Motor de observación de entorno o captura de telemetría previa al razonamiento."""

    @property
    def engine_type(self) -> str:
        """Tipo de motor cognitivo estandarizado como observer."""
        return "observer"


class PlannerEngine(BaseEngine, ABC):
    """Motor de formulación y descomposición de planes de acción."""

    @property
    def engine_type(self) -> str:
        """Tipo de motor cognitivo estandarizado como planner."""
        return "planner"


class VerifierEngine(BaseEngine, ABC):
    """Motor de verificación activa de resultados tras la ejecución de herramientas."""

    @property
    def engine_type(self) -> str:
        """Tipo de motor cognitivo estandarizado como verifier."""
        return "verifier"


class BasePlugin(ABC):
    """Clase base abstracta obligatoria para todos los plugins de jg_agente.

    Define los contratos de registro de capacidades (tools, engines, modelos)
    así como los hooks de ciclo de vida e inspección de salud.
    """

    @abstractmethod
    def get_plugin_metadata(self) -> PluginMetadata:
        """Retorna los metadatos canónicos del plugin."""
        ...

    @abstractmethod
    def register_tools(self) -> list[AgentTool]:
        """Retorna la lista de AgentTool provistas por el plugin para su integración en el Core."""
        ...

    @abstractmethod
    def register_engines(self) -> dict[str, BaseEngine]:
        """Retorna los motores de dominio registrados por el plugin, mapeados por nombre o tipo."""
        ...

    def register_models(self) -> dict[str, type[BaseModel]]:
        """Hook opcional para declarar modelos Pydantic o extensiones de esquema del dominio."""
        return {}

    async def startup(self) -> None:  # noqa: B027
        """Hook asíncrono ejecutado durante el arranque del agente para inicializar el plugin."""
        pass

    async def shutdown(self) -> None:  # noqa: B027
        """Hook asíncrono ejecutado durante el apagado del agente para liberar recursos."""
        pass

    async def health_check(self) -> dict[str, Any]:
        """Verifica la operatividad del plugin y sus dependencias externas."""
        return {"status": "ok", "plugin": self.name}

    @property
    def name(self) -> str:
        """Acceso directo al nombre del plugin desde sus metadatos."""
        return self.get_plugin_metadata().name

    @property
    def version(self) -> str:
        """Acceso directo a la versión del plugin desde sus metadatos."""
        return self.get_plugin_metadata().version

    async def __aenter__(self) -> Self:
        """Soporte para gestor de contexto asíncrono con startup automático."""
        await self.startup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Soporte para gestor de contexto asíncrono con shutdown automático."""
        await self.shutdown()


# Interoperabilidad nativa con jg_sdk (SDK desacoplado de plugins)
try:
    import jg_sdk.contracts as _sdk_contracts

    BasePlugin.register(_sdk_contracts.BasePlugin)  # type: ignore[type-abstract]
    BaseEngine.register(_sdk_contracts.BaseEngine)  # type: ignore[type-abstract]
except Exception:
    pass
