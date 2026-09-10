"""Tests unitarios y de integración para NewsTool y NewsArgs en jg_plugin_conversational."""

import socket
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.registry import CapabilityRegistry
from app.models.tools import AgentTool, RiskLevel, ToolResult
from app.security.ssrf import SSRFValidationError
from jg_plugin_conversational.news import (
    NewsArgs,
    create_news_tool,
    get_news_fn,
)
from jg_plugin_conversational.plugin import ConversationalPlugin


def test_news_args_valid() -> None:
    """Verifica que NewsArgs acepta temáticas válidas y valores por defecto."""
    args_default = NewsArgs()
    assert args_default.topic == "general"
    assert args_default.limit == 3

    valid_topics = ["economia", "deportes", "internacional", "politica-nacional"]
    for topic in valid_topics:
        args = NewsArgs(topic=topic, limit=5)
        assert args.topic == topic
        assert args.limit == 5


def test_news_args_rejection_anti_ssrf_and_invalid() -> None:
    """Verifica el rechazo estricto de URLs, IPs y comandos maliciosos anti-SSRF."""
    invalid_topics = [
        "http://169.254.169.254/latest/meta-data/",
        "https://malicious.example.com",
        "169.254.169.254",
        "economia; cat /etc/passwd",
        "deportes && whoami",
        "<script>alert(1)</script>",
        "A" * 60,  # Excede max_length 50
    ]
    for inv in invalid_topics:
        with pytest.raises((ValidationError, ValueError)):
            NewsArgs(topic=inv)

    # Límites inválidos
    with pytest.raises(ValidationError):
        NewsArgs(limit=0)
    with pytest.raises(ValidationError):
        NewsArgs(limit=15)


def test_news_tool_contract_attributes() -> None:
    """Verifica que NewsTool satisface todos los requisitos del contrato AgentTool."""
    tool = create_news_tool()

    assert isinstance(tool, AgentTool)
    assert tool.name == "get_news"
    assert tool.category == "news"
    assert tool.version == "1.0.0"
    assert tool.args_schema is NewsArgs
    assert callable(tool.func)
    assert tool.risk_level == RiskLevel.LOW
    assert tool.read_only is True
    assert tool.reversible is False
    assert tool.idempotent is True
    assert tool.makes_http_requests is True
    assert tool.timeout_sec == 5.0
    assert tool.rollback_func is None


def test_news_simulated_execution() -> None:
    """Verifica la ejecución determinista en modo simulación (offline o fallback)."""
    tool = create_news_tool()
    args = NewsArgs(topic="economia", limit=2)

    # Forzar fallback simulado simulando error o sin respuesta HTTP
    with patch("httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.get.side_effect = Exception(
            "Offline mode"
        )
        result = tool.func(args)

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "Últimas noticias de actualidad" in result.output
    assert result.duration_ms >= 0.0
    assert result.metadata.get("topic") == "economia"
    assert result.metadata.get("source") == "simulated"
    assert len(result.metadata.get("articles", [])) == 2

    # Verificación de resolución de seguridad SEC-06:
    # No deben existir pseudo-prompts o instrucciones para el LLM en el texto devuelto
    forbidden_prompts = ["instrucción para ti", "lee únicamente", "como la herramienta"]
    for fp in forbidden_prompts:
        assert fp not in result.output.lower()


def test_news_xml_parsing_mocked_http() -> None:
    """Verifica el parseo seguro de XML RSS y extracción limpia de titulares y descripciones."""
    sample_xml = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
        <channel>
            <title>Europa Press - Portada</title>
            <item>
                <title>Aprobado el nuevo paquete de medidas para el sector científico</title>
                <description><![CDATA[El consejo aprueba un impulso presupuestario sin precedentes.]]></description>
                <link>https://www.europapress.es/ciencia/noticia-1.html</link>
            </item>
            <item>
                <title>La cumbre de ciberseguridad destaca la resiliencia en infraestructuras críticas</title>
                <description>Expertos internacionales presentan nuevos estándares de defensa.</description>
                <link>https://www.europapress.es/nacional/noticia-2.html</link>
            </item>
        </channel>
    </rss>
    """.encode()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = sample_xml

    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = mock_resp

    with (
        patch(
            "socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("195.55.100.1", 443))],
        ),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value = mock_client_instance
        result = get_news_fn(NewsArgs(topic="general", limit=2))

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "Últimas noticias de Europa Press" in result.output
    assert "Aprobado el nuevo paquete de medidas" in result.output
    assert result.metadata.get("source") == "europapress_rss"
    assert len(result.metadata.get("articles", [])) == 2
    assert (
        result.metadata["articles"][0]["title"]
        == "Aprobado el nuevo paquete de medidas para el sector científico"
    )


def test_news_offline_dns_failure_fallback() -> None:
    """Verifica que la ausencia de DNS en entornos offline o aislados conmuta a simulación."""
    with patch(
        "socket.getaddrinfo",
        side_effect=socket.gaierror(-3, "Temporary failure in name resolution"),
    ):
        result = get_news_fn(NewsArgs(topic="deportes", limit=2))

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "Últimas noticias de actualidad" in result.output
    assert result.metadata.get("source") == "simulated"
    assert result.metadata.get("topic") == "deportes"
    assert len(result.metadata.get("articles", [])) == 2


def test_news_real_ssrf_violation_raises() -> None:
    """Verifica que una violación real de SSRF (ej. IP privada) eleva SSRFValidationError y no simulación."""
    with (
        patch(
            "socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ),
        pytest.raises(SSRFValidationError),
    ):
        get_news_fn(NewsArgs(topic="general", limit=2))


def test_conversational_plugin_register_news_tool() -> None:
    """Verifica que ConversationalPlugin expone get_news y get_weather."""
    plugin = ConversationalPlugin()
    tools = plugin.register_tools()

    tool_names = [t.name for t in tools]
    assert "get_weather" in tool_names
    assert "get_news" in tool_names
    assert len(tools) == 2


def test_capability_registry_news_registration() -> None:
    """Verifica el registro en cascada de NewsTool en CapabilityRegistry."""
    registry = CapabilityRegistry()
    plugin = ConversationalPlugin()

    registry.register_plugin(plugin)

    assert registry.has_tool("get_news") is True
    assert registry.has_tool("get_weather") is True

    tool = registry.get_tool("get_news")
    assert tool is not None
    assert tool.name == "get_news"
    assert tool.category == "news"
    assert tool.read_only is True

    summary = registry.get_capabilities_summary()
    assert summary["tools_count"] == 2
    names = [t["name"] for t in summary["tools"]]
    assert "get_weather" in names
    assert "get_news" in names
