# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios para la exposición de input_schema en CapabilityRegistry y /capabilities."""

from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.core.registry import CapabilityRegistry
from app.models.tools import AgentTool, RiskLevel, ToolResult


class QueryFilterType(StrEnum):
    ALL = "all"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ComplexToolSchema(BaseModel):
    query: str = Field(..., description="Término de búsqueda principal")
    limit: int = Field(default=10, ge=1, le=100, description="Cantidad máxima de resultados")
    tags: list[str] = Field(default_factory=list, description="Etiquetas de filtrado")
    filter_type: QueryFilterType = Field(
        default=QueryFilterType.ACTIVE, description="Tipo de filtro"
    )


def test_registry_extracts_pydantic_input_schema() -> None:
    """Verifica que el registry extraiga el model_json_schema completo de las tools."""
    registry = CapabilityRegistry()

    def dummy_func(**kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output=kwargs)

    tool_with_schema = AgentTool(
        name="search_complex_records",
        description="Busca registros con filtros complejos",
        args_schema=ComplexToolSchema,
        func=dummy_func,
        risk_level=RiskLevel.LOW,
    )

    tool_without_schema = AgentTool(
        name="simple_ping",
        description="Ping simple sin argumentos",
        func=dummy_func,
        risk_level=RiskLevel.LOW,
    )

    registry.register_tool(tool_with_schema)
    registry.register_tool(tool_without_schema)

    summary = registry.get_capabilities_summary()
    assert summary["tools_count"] == 2

    tools_by_name = {t["name"]: t for t in summary["tools"]}

    # 1. Herramienta con esquema Pydantic
    complex_summary = tools_by_name["search_complex_records"]
    assert "input_schema" in complex_summary
    input_schema = complex_summary["input_schema"]
    assert input_schema.get("type") == "object"
    assert "properties" in input_schema
    props = input_schema["properties"]
    assert "query" in props
    assert "limit" in props
    assert "tags" in props
    assert "filter_type" in props
    assert "required" in input_schema
    assert "query" in input_schema["required"]

    # 2. Herramienta sin esquema Pydantic
    simple_summary = tools_by_name["simple_ping"]
    assert "input_schema" in simple_summary
    assert simple_summary["input_schema"].get("type") == "object"
    assert simple_summary["input_schema"].get("additionalProperties") is True


@pytest.mark.asyncio
async def test_capabilities_endpoint_returns_input_schema() -> None:
    """Verifica que el endpoint /capabilities sirva el input_schema a clientes HTTP."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    registry = CapabilityRegistry()

    def dummy_func(**kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="ok")

    registry.register_tool(
        AgentTool(
            name="test_endpoint_tool",
            description="Herramienta de prueba de endpoint",
            args_schema=ComplexToolSchema,
            func=dummy_func,
        )
    )

    app.state.registry = registry

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        matching_tools = [t for t in data["tools"] if t["name"] == "test_endpoint_tool"]
        assert len(matching_tools) == 1
        tool_data = matching_tools[0]
        assert "input_schema" in tool_data
        assert "query" in tool_data["input_schema"]["properties"]
