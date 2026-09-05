"""Tests unitarios y de integración para el paquete jg_plugin_conversational."""

import ast
from pathlib import Path

import pytest

from app.core.plugin_manager import PluginManager
from app.core.registry import CapabilityRegistry
from app.plugins.base import BasePlugin, PluginMetadata
from jg_plugin_conversational import PLUGIN_CLASS, ConversationalPlugin, __version__


def test_import_and_plugin_class_contract() -> None:
    """Verifica que el paquete se importa independientemente y expone PLUGIN_CLASS válido."""
    assert PLUGIN_CLASS is not None
    assert issubclass(PLUGIN_CLASS, BasePlugin)
    assert PLUGIN_CLASS is ConversationalPlugin
    assert __version__ == "0.1.0"

    plugin = PLUGIN_CLASS()
    assert isinstance(plugin, BasePlugin)
    assert plugin.name == "conversational"


def test_plugin_metadata() -> None:
    """Valida los metadatos canónicos del plugin conversacional."""
    plugin = ConversationalPlugin()
    meta = plugin.get_plugin_metadata()

    assert isinstance(meta, PluginMetadata)
    assert meta.name == "conversational"
    assert meta.version == "0.1.0"
    assert meta.dependencies == []
    assert meta.jg_agente_version_min == "0.1.0"
    assert "conversational" in meta.tags
    assert "nlp" in meta.tags


def test_register_tools_and_engines_contracts() -> None:
    """Valida los métodos obligatorios de registro de herramientas y motores."""
    plugin = ConversationalPlugin()

    tools = plugin.register_tools()
    assert isinstance(tools, list)
    assert len(tools) == 0

    engines = plugin.register_engines()
    assert isinstance(engines, dict)
    assert len(engines) == 0

    models = plugin.register_models()
    assert isinstance(models, dict)


@pytest.mark.asyncio
async def test_async_lifecycle() -> None:
    """Valida el ciclo de vida asíncrono con startup, shutdown y health_check."""
    plugin = ConversationalPlugin()
    assert plugin._is_started is False

    async with plugin:
        assert plugin._is_started is True
        health = await plugin.health_check()
        assert health["status"] == "ok"
        assert health["plugin"] == "conversational"
        assert health["version"] == "0.1.0"
        assert health["started"] is True

    assert plugin._is_started is False


def test_strict_isolation_no_devops_or_asterisk() -> None:
    """Garantiza ausencia total de dependencias o imports hacia DevOps o Asterisk directo."""
    plugin_file = Path(__file__).parent.parent / "plugin.py"
    assert plugin_file.exists(), f"No se encontró el archivo de plugin en {plugin_file}"

    tree = ast.parse(plugin_file.read_text(encoding="utf-8"))
    forbidden_terms = ["docker", "kubernetes", "k8s", "devops", "asterisk", "ari", "pjsip"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for term in forbidden_terms:
                    assert term not in alias.name.lower(), (
                        f"Import indebido detectado en plugin conversacional: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            for term in forbidden_terms:
                assert term not in mod_name.lower(), (
                    f"ImportFrom indebido detectado en plugin conversacional: {mod_name}"
                )


def test_plugin_manager_autodiscovery() -> None:
    """Verifica que PluginManager descubre y carga jg_plugin_conversational automáticamente."""
    plugins_root = Path(__file__).parent.parent.parent
    registry = CapabilityRegistry()
    pm = PluginManager(registry=registry, plugins_dir=plugins_root)

    discovered = pm.discover_local_plugins(directory=plugins_root)
    assert any(
        cls is ConversationalPlugin or cls.__name__ == "ConversationalPlugin" for cls in discovered
    )

    loaded = pm.load_plugins(plugins_dir=plugins_root, load_entrypoints=False, load_local=True)
    assert any(p.name == "conversational" for p in loaded)
    assert registry.get_plugin("conversational") is not None
