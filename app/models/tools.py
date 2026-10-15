# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Definición canónica de herramientas y resultados para jg_agente.

Este módulo implementa los contratos formales AgentTool y ToolResult integrados
con el SDK desacoplado (jg_sdk.contracts), añadiendo la capacidad de adaptación
a LangChain (as_langchain_tool) requerida por el motor cognitivo.
"""

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

try:
    from jg_sdk.contracts import (
        AgentTool as SDKAgentTool,
    )
    from jg_sdk.contracts import (
        RiskLevel,
        ToolResult,
        ToolType,
    )
except ImportError:
    import concurrent.futures
    import time
    from collections.abc import Callable
    from enum import StrEnum

    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

    class RiskLevel(StrEnum):  # type: ignore[no-redef]
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        CRITICAL = "critical"

    class ToolType(StrEnum):  # type: ignore[no-redef]
        OBSERVER = "observer"
        ACTUATOR = "actuator"
        VERIFIER = "verifier"
        READ = "read"
        MUTATION = "mutation"

    class ToolResult(BaseModel):  # type: ignore[no-redef]
        model_config = ConfigDict(extra="allow")
        success: bool = Field(..., description="Indica si la ejecución concluyó exitosamente")
        output: Any = Field(
            default="", description="Salida, datos o texto producido por la herramienta"
        )
        error: str | None = Field(
            default=None, description="Mensaje de error si la ejecución falló"
        )
        duration_ms: float = Field(
            default=0.0, ge=0.0, description="Tiempo de ejecución en milisegundos"
        )
        metadata: dict[str, Any] = Field(default_factory=dict, description="Metadatos de contexto")
        rollback_context: dict[str, Any] | None = Field(
            default=None, description="Datos de compensación"
        )

        def __str__(self) -> str:
            if self.success:
                return str(self.output)
            return f"Error: {self.error or self.output}"

    class SDKAgentTool(BaseModel):  # type: ignore[no-redef]
        model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")
        name: str = Field(..., min_length=1)
        description: str = Field(..., min_length=1)
        category: str = Field(default="general", min_length=1)
        version: str = Field(default="1.0.0")
        args_schema: type[BaseModel] | None = Field(default=None)
        func: Callable[..., Any] = Field(...)
        risk_level: RiskLevel = Field(default=RiskLevel.LOW)
        required_permissions: list[str] = Field(default_factory=list)
        tool_type: ToolType = Field(default=ToolType.OBSERVER)
        read_only: bool = Field(default=True)
        reversible: bool = Field(default=False)
        idempotent: bool = Field(default=True)
        makes_http_requests: bool = Field(default=False)
        allow_failure: bool = Field(default=False)
        timeout_sec: float = Field(default=30.0, gt=0.0)
        rollback_func: Callable[[dict[str, Any]], ToolResult] | None = Field(default=None)

        @field_validator("func")
        @classmethod
        def validate_func_callable(cls, v: Any) -> Any:
            if not callable(v):
                raise ValueError("El campo 'func' debe ser un invocable.")
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
        def validate_reversible_and_rollback(self) -> Any:
            if self.reversible and self.rollback_func is None:
                raise ValueError("Herramientas reversibles requieren rollback_func.")
            if self.rollback_func is not None:
                self.reversible = True
            return self

        def run(self, *args: Any, **kwargs: Any) -> ToolResult:
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
                    return ToolResult(success=True, output=res, duration_ms=round(duration, 2))
                elif isinstance(res, bool):
                    return ToolResult(
                        success=res,
                        output="Operación exitosa" if res else "Operación fallida",
                        duration_ms=round(duration, 2),
                    )
                else:
                    return ToolResult(success=True, output=res, duration_ms=round(duration, 2))
            except TimeoutError:
                duration = (time.perf_counter() - start_time) * 1000
                return ToolResult(
                    success=False,
                    output="",
                    error=f"TimeoutError: {self.name} superó {timeout}s",
                    duration_ms=round(duration, 2),
                    metadata={"timeout_sec": timeout, "timed_out": True},
                )
            except Exception as exc:
                duration = (time.perf_counter() - start_time) * 1000
                return ToolResult(
                    success=False, output="", error=str(exc), duration_ms=round(duration, 2)
                )

        def rollback(self, rollback_context: dict[str, Any]) -> ToolResult:
            if not self.reversible or self.rollback_func is None:
                return ToolResult(
                    success=False,
                    error="NO_ROLLBACK_AVAILABLE",
                    output="Operación no reversible",
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
