"""Definición canónica de herramientas y resultados para jg_agente.

Este módulo implementa los contratos formales AgentTool y ToolResult,
estableciendo la especificación estricta para capacidades ejecutables,
análisis de riesgo, esquemas de argumentos, y capacidades de compensación.
"""

import concurrent.futures
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RiskLevel(StrEnum):
    """Niveles de riesgo operativo para la ejecución de herramientas."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolType(StrEnum):
    """Clasificación funcional de herramientas."""

    OBSERVER = "observer"
    ACTUATOR = "actuator"
    VERIFIER = "verifier"
    READ = "read"
    MUTATION = "mutation"


class ToolResult(BaseModel):
    """Resultado estructurado y normalizado devuelto tras ejecutar una herramienta."""

    model_config = ConfigDict(extra="allow")

    success: bool = Field(..., description="Indica si la ejecución concluyó exitosamente")
    output: Any = Field(
        default="", description="Salida, datos o texto producido por la herramienta"
    )
    error: str | None = Field(default=None, description="Mensaje de error si la ejecución falló")
    duration_ms: float = Field(
        default=0.0, ge=0.0, description="Tiempo de ejecución en milisegundos"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadatos de contexto, auditoría o trazabilidad",
    )
    rollback_context: dict[str, Any] | None = Field(
        default=None,
        description="Datos de estado requeridos para compensar o revertir los efectos",
    )

    def __str__(self) -> str:
        if self.success:
            return str(self.output)
        return f"Error: {self.error or self.output}"


class AgentTool(BaseModel):
    """Contrato definitivo y descriptor de capacidades de una herramienta en jg_agente."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    name: str = Field(..., min_length=1, description="Identificador único de la herramienta")
    description: str = Field(
        ..., min_length=1, description="Descripción para el function calling del LLM"
    )
    category: str = Field(..., min_length=1, description="Categoría lógica de la herramienta")
    version: str = Field(default="1.0.0", description="Versión semántica del descriptor")

    args_schema: type[BaseModel] | None = Field(
        default=None,
        description="Esquema Pydantic de argumentos requerido por el LLM",
    )
    func: Callable[..., Any] = Field(
        ...,
        description="Función ejecutable que implementa la herramienta",
    )

    risk_level: RiskLevel = Field(
        default=RiskLevel.LOW,
        description="Nivel de riesgo operativo evaluado por el SecurityGuard",
    )
    required_permissions: list[str] = Field(
        default_factory=list,
        description="Permisos RBAC requeridos para ejecutar la herramienta",
    )

    tool_type: ToolType = Field(
        default=ToolType.OBSERVER,
        description="Rol funcional de la herramienta (observer, actuator, verifier)",
    )
    read_only: bool = Field(
        default=True,
        description="Indica si la herramienta carece de efectos secundarios en el entorno",
    )
    reversible: bool = Field(
        default=False,
        description="Indica si la herramienta puede compensar sus cambios ante fallos",
    )
    idempotent: bool = Field(
        default=True,
        description="Indica si ejecutarla múltiples veces produce el mismo resultado",
    )
    makes_http_requests: bool = Field(
        default=False,
        description="Indica si realiza peticiones de red salientes (sujeto a SSRF protection)",
    )

    timeout_sec: float = Field(
        default=30.0,
        gt=0.0,
        description="Tiempo límite de ejecución en segundos",
    )
    rollback_func: Callable[[dict[str, Any]], ToolResult] | None = Field(
        default=None,
        description="Función de compensación invocable ante fallos del flujo",
    )

    @field_validator("func")
    @classmethod
    def validate_func_callable(cls, v: Any) -> Any:
        if not callable(v):
            raise ValueError("El campo 'func' debe ser un invocable (función o método).")
        return v

    @field_validator("rollback_func")
    @classmethod
    def validate_rollback_func_callable(cls, v: Any) -> Any:
        if v is not None and not callable(v):
            raise ValueError("El campo 'rollback_func' debe ser un invocable o None.")
        return v

    @field_validator("args_schema")
    @classmethod
    def validate_args_schema_type(cls, v: Any) -> Any:
        if v is not None and not (isinstance(v, type) and issubclass(v, BaseModel)):
            raise ValueError(
                "El campo 'args_schema' debe ser una subclase de Pydantic BaseModel o None."
            )
        return v

    @model_validator(mode="after")
    def validate_reversible_and_rollback(self) -> "AgentTool":
        if self.reversible and self.rollback_func is None:
            raise ValueError(
                "Las herramientas configuradas como reversibles (reversible=True) "
                "deben proporcionar obligatoriamente un 'rollback_func' válido para compensación."
            )
        if self.rollback_func is not None:
            self.reversible = True
        return self

    def run(self, *args: Any, **kwargs: Any) -> ToolResult:
        """Ejecuta la herramienta de forma síncrona respetando timeout_sec."""
        start_time = time.perf_counter()
        timeout = self.timeout_sec or 30.0

        def _exec() -> Any:
            return self.func(*args, **kwargs)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_exec)
                res = future.result(timeout=timeout)

            duration = (time.perf_counter() - start_time) * 1000

            if isinstance(res, ToolResult):
                if res.duration_ms <= 0.0:
                    res.duration_ms = round(duration, 2)
                return res
            elif isinstance(res, str):
                return ToolResult(
                    success=True,
                    output=res,
                    duration_ms=round(duration, 2),
                )
            elif isinstance(res, bool):
                return ToolResult(
                    success=res,
                    output="Operación exitosa" if res else "Operación fallida",
                    duration_ms=round(duration, 2),
                )
            else:
                return ToolResult(
                    success=True,
                    output=res,
                    duration_ms=round(duration, 2),
                )
        except TimeoutError:
            duration = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                success=False,
                output="",
                error=f"TimeoutError: La herramienta '{self.name}' superó el tiempo límite de {timeout}s",
                duration_ms=round(duration, 2),
                metadata={"timeout_sec": timeout, "timed_out": True},
            )
        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                success=False,
                output="",
                error=str(exc),
                duration_ms=round(duration, 2),
            )

    def rollback(self, rollback_context: dict[str, Any]) -> ToolResult:
        """Ejecuta la compensación asociada a la herramienta si está definida.

        Si la herramienta no es reversible o no cuenta con función de compensación,
        emite un ToolResult con error explícito 'NO_ROLLBACK_AVAILABLE'.
        """
        if not self.reversible or self.rollback_func is None:
            return ToolResult(
                success=False,
                error="NO_ROLLBACK_AVAILABLE",
                output="Operación no reversible: la herramienta no dispone de compensador registrado.",
                metadata={"reversible": False},
            )

        start_time = time.perf_counter()
        try:
            res = self.rollback_func(rollback_context)
            duration = (time.perf_counter() - start_time) * 1000

            if isinstance(res, ToolResult):
                if res.duration_ms <= 0.0:
                    res.duration_ms = round(duration, 2)
                res.metadata.setdefault("rollback_executed", True)
                return res
            elif isinstance(res, bool):
                return ToolResult(
                    success=res,
                    output="Compensación completada exitosamente."
                    if res
                    else "Compensación fallida.",
                    duration_ms=round(duration, 2),
                    metadata={"rollback_executed": True},
                )
            elif isinstance(res, str):
                return ToolResult(
                    success=True,
                    output=res,
                    duration_ms=round(duration, 2),
                    metadata={"rollback_executed": True},
                )
            else:
                return ToolResult(
                    success=True,
                    output=str(res) if res is not None else "Compensación completada.",
                    duration_ms=round(duration, 2),
                    metadata={"rollback_executed": True},
                )
        except Exception as exc:
            duration = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                success=False,
                output="",
                error=f"Error durante la compensación: {exc}",
                duration_ms=round(duration, 2),
                metadata={"rollback_executed": False, "exception": str(exc)},
            )

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
