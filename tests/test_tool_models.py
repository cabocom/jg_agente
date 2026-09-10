"""Tests unitarios para la especificación formal de AgentTool y ToolResult."""

from typing import Any

import pytest
from pydantic import BaseModel, Field, ValidationError

from app.models import (
    AgentTool,
    RiskLevel,
    ToolResult,
    ToolType,
)


class DummyInputSchema(BaseModel):
    """Esquema de prueba para argumentos de herramientas."""

    param_a: str = Field(..., description="Parámetro alfa")
    param_b: int = Field(default=10, description="Parámetro beta")


def sample_calculator(param_a: str, param_b: int = 10) -> str:
    return f"{param_a}:{param_b * 2}"


def sample_failing_function(param_a: str, param_b: int = 10) -> str:
    raise RuntimeError("Fallo forzado en la ejecución")


def sample_rollback_handler(context: dict[str, Any]) -> ToolResult:
    return ToolResult(
        success=True,
        output=f"Compensado {context.get('item_id')}",
        metadata={"rollback_executed": True},
    )


class TestToolResult:
    """Pruebas del modelo ToolResult."""

    def test_tool_result_success(self) -> None:
        res = ToolResult(
            success=True,
            output={"status": "ok"},
            duration_ms=45.2,
            metadata={"source": "test"},
        )
        assert res.success is True
        assert res.output == {"status": "ok"}
        assert res.duration_ms == 45.2
        assert res.error is None
        assert res.rollback_context is None
        assert "status" in str(res)

    def test_tool_result_with_rollback_context(self) -> None:
        res = ToolResult(
            success=True,
            output="Container started",
            rollback_context={"container_id": "c-999"},
        )
        assert res.rollback_context == {"container_id": "c-999"}

    def test_tool_result_failure_string_representation(self) -> None:
        res = ToolResult(
            success=False,
            output="Inaccessible",
            error="Connection refused",
        )
        assert res.success is False
        assert str(res) == "Error: Connection refused"


class TestAgentTool:
    """Pruebas del contrato AgentTool."""

    def test_agent_tool_instantiation_minimal(self) -> None:
        tool = AgentTool(
            name="test_tool",
            description="Herramienta de prueba",
            category="testing",
            func=sample_calculator,
        )
        assert tool.name == "test_tool"
        assert tool.description == "Herramienta de prueba"
        assert tool.category == "testing"
        assert tool.version == "1.0.0"
        assert tool.risk_level == RiskLevel.LOW
        assert tool.tool_type == ToolType.OBSERVER
        assert tool.read_only is True
        assert tool.reversible is False
        assert tool.idempotent is True
        assert tool.makes_http_requests is False
        assert tool.timeout_sec == 30.0
        assert tool.args_schema is None
        assert tool.rollback_func is None

    def test_agent_tool_with_schema_and_risk(self) -> None:
        tool = AgentTool(
            name="mutate_infra",
            description="Modifica infraestructura",
            category="infrastructure",
            args_schema=DummyInputSchema,
            func=sample_calculator,
            risk_level=RiskLevel.HIGH,
            tool_type=ToolType.ACTUATOR,
            read_only=False,
            required_permissions=["infra:write"],
            timeout_sec=60.0,
        )
        assert tool.args_schema is DummyInputSchema
        assert tool.risk_level == RiskLevel.HIGH
        assert tool.tool_type == ToolType.ACTUATOR
        assert tool.read_only is False
        assert tool.required_permissions == ["infra:write"]
        assert tool.timeout_sec == 60.0

    def test_agent_tool_automatic_reversible_when_rollback_func_provided(self) -> None:
        tool = AgentTool(
            name="reversible_tool",
            description="Herramienta con compensación",
            category="database",
            func=sample_calculator,
            rollback_func=sample_rollback_handler,
        )
        assert tool.rollback_func is not None
        assert tool.reversible is True

    def test_agent_tool_rejects_non_callable_func(self) -> None:
        with pytest.raises(ValidationError):
            AgentTool(
                name="invalid_tool",
                description="Desc",
                category="test",
                func="not_a_callable",  # type: ignore[arg-type]
            )

    def test_agent_tool_rejects_invalid_args_schema(self) -> None:
        with pytest.raises(ValidationError):
            AgentTool(
                name="invalid_schema_tool",
                description="Desc",
                category="test",
                args_schema=dict,  # type: ignore[arg-type]
                func=sample_calculator,
            )

    def test_agent_tool_rejects_negative_timeout(self) -> None:
        with pytest.raises(ValidationError):
            AgentTool(
                name="timeout_tool",
                description="Desc",
                category="test",
                func=sample_calculator,
                timeout_sec=-5.0,
            )

    def test_agent_tool_run_successful(self) -> None:
        tool = AgentTool(
            name="calc_tool",
            description="Calculadora",
            category="math",
            args_schema=DummyInputSchema,
            func=sample_calculator,
        )
        result = tool.run(param_a="test", param_b=5)
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.output == "test:10"
        assert result.duration_ms >= 0.0

    def test_agent_tool_run_exception_handling(self) -> None:
        tool = AgentTool(
            name="failing_tool",
            description="Herramienta que falla",
            category="test",
            func=sample_failing_function,
        )
        result = tool.run(param_a="error")
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.error is not None
        assert "Fallo forzado" in result.error

    def test_agent_tool_run_timeout_handling(self) -> None:
        import time

        def _slow_fn(**kwargs: Any) -> str:
            time.sleep(0.4)
            return "ok"

        tool = AgentTool(
            name="slow_tool",
            description="Herramienta lenta",
            category="test",
            func=_slow_fn,
            timeout_sec=0.1,
        )
        result = tool.run()
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "TimeoutError" in (result.error or "")
        assert result.metadata.get("timed_out") is True

    def test_agent_tool_rollback_execution(self) -> None:
        tool = AgentTool(
            name="rollbackable",
            description="Herramienta con rollback",
            category="system",
            func=sample_calculator,
            rollback_func=sample_rollback_handler,
        )
        rb_res = tool.rollback({"item_id": "item-101"})
        assert rb_res.success is True
        assert "item-101" in str(rb_res.output)
        assert rb_res.metadata["rollback_executed"] is True

    def test_agent_tool_reversible_true_without_rollback_func_raises_validation_error(
        self,
    ) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AgentTool(
                name="invalid_reversible",
                description="Herramienta sin compensador",
                category="test",
                func=sample_calculator,
                reversible=True,
                rollback_func=None,
            )
        assert "rollback_func" in str(exc_info.value)

    def test_agent_tool_rollback_when_no_rollback_func(self) -> None:
        tool = AgentTool(
            name="no_rollback",
            description="Sin compensación",
            category="system",
            func=sample_calculator,
        )
        rb_res = tool.rollback({"item_id": "item-101"})
        assert rb_res.success is False
        assert rb_res.error == "NO_ROLLBACK_AVAILABLE"
        assert rb_res.metadata["reversible"] is False

    def test_agent_tool_rollback_exception_handling(self) -> None:
        def failing_rollback(context: dict[str, Any]) -> ToolResult:
            raise RuntimeError("Fallo crítico en el compensador")

        tool = AgentTool(
            name="failing_rollback_tool",
            description="Herramienta con compensador fallido",
            category="system",
            func=sample_calculator,
            rollback_func=failing_rollback,
        )
        rb_res = tool.rollback({"item_id": "item-202"})
        assert rb_res.success is False
        assert rb_res.error is not None
        assert "Fallo crítico en el compensador" in rb_res.error
        assert rb_res.metadata["rollback_executed"] is False

    def test_agent_tool_rollback_primitive_returns(self) -> None:
        def bool_rollback(context: dict[str, Any]) -> bool:
            return True

        tool = AgentTool(
            name="bool_rollback_tool",
            description="Compensador booleano",
            category="system",
            func=sample_calculator,
            rollback_func=bool_rollback,  # type: ignore[arg-type]
        )
        rb_res = tool.rollback({"item_id": "item-303"})
        assert rb_res.success is True
        assert rb_res.metadata["rollback_executed"] is True

    def test_agent_tool_as_langchain_tool(self) -> None:
        tool = AgentTool(
            name="lc_tool",
            description="Herramienta LangChain",
            category="integration",
            args_schema=DummyInputSchema,
            func=sample_calculator,
        )
        lc_tool = tool.as_langchain_tool()
        assert lc_tool.name == "lc_tool"
        assert lc_tool.description == "Herramienta LangChain"

        output = lc_tool.invoke({"param_a": "alpha", "param_b": 2})
        assert "alpha:4" in str(output)
