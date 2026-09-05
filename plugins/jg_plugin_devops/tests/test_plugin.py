"""Tests unitarios y de contrato para jg_plugin_devops."""

import ast
from pathlib import Path

import pytest

from app.core.plugin_manager import PluginManager
from app.core.registry import CapabilityRegistry
from app.plugins.base import BasePlugin, PluginMetadata
from jg_plugin_devops import (
    PLUGIN_CLASS,
    DevOpsPlugin,
    InfraSnapshot,
    __version__,
)


def test_import_and_plugin_class_contract() -> None:
    """Verifica que el paquete se importa y expone PLUGIN_CLASS válido según BasePlugin."""
    assert PLUGIN_CLASS is not None
    assert issubclass(PLUGIN_CLASS, BasePlugin)
    assert PLUGIN_CLASS is DevOpsPlugin
    assert __version__ == "0.1.0"

    plugin = PLUGIN_CLASS()
    assert isinstance(plugin, BasePlugin)
    assert plugin.name == "devops"
    assert plugin.version == "0.1.0"


def test_plugin_metadata() -> None:
    """Valida los metadatos canónicos del plugin DevOps."""
    plugin = DevOpsPlugin()
    meta = plugin.get_plugin_metadata()

    assert isinstance(meta, PluginMetadata)
    assert meta.name == "devops"
    assert meta.version == "0.1.0"
    assert meta.dependencies == []
    assert meta.jg_agente_version_min == "0.1.0"
    assert "devops" in meta.tags
    assert "infrastructure" in meta.tags
    assert "sre" in meta.tags


def test_register_tools_engines_models_contracts() -> None:
    """Valida los métodos obligatorios de registro de herramientas, motores y modelos."""
    plugin = DevOpsPlugin()

    tools = plugin.register_tools()
    assert isinstance(tools, list)

    engines = plugin.register_engines()
    assert isinstance(engines, dict)

    models = plugin.register_models()
    assert isinstance(models, dict)
    assert "InfraSnapshot" in models
    assert models["InfraSnapshot"] is InfraSnapshot


@pytest.mark.asyncio
async def test_async_lifecycle() -> None:
    """Valida el ciclo de vida asíncrono con startup, shutdown y health_check."""
    plugin = DevOpsPlugin()
    assert plugin._is_started is False

    async with plugin:
        assert plugin._is_started is True
        health = await plugin.health_check()
        assert health["status"] == "ok"
        assert health["plugin"] == "devops"
        assert health["version"] == "0.1.0"
        assert health["started"] is True

    assert plugin._is_started is False


def test_plugin_manager_autodiscovery() -> None:
    """Verifica que PluginManager descubre y carga jg_plugin_devops y convive con otros plugins."""
    plugins_root = Path(__file__).parent.parent.parent
    registry = CapabilityRegistry()
    pm = PluginManager(registry=registry, plugins_dir=plugins_root)

    discovered = pm.discover_local_plugins(directory=plugins_root)
    assert any(cls is DevOpsPlugin or cls.__name__ == "DevOpsPlugin" for cls in discovered)

    loaded = pm.load_plugins(plugins_dir=plugins_root, load_entrypoints=False, load_local=True)
    assert any(p.name == "devops" for p in loaded)
    assert registry.get_plugin("devops") is not None


def test_strict_core_isolation() -> None:
    """Garantiza que el Core de jg_agente no importa jg_plugin_devops."""
    repo_root = Path(__file__).parent.parent.parent.parent
    core_dir = repo_root / "app"
    py_files = list(core_dir.rglob("*.py"))
    assert py_files, "No se encontraron archivos en app/"

    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "jg_plugin_devops" not in alias.name, (
                        f"Core depende indebidamente de jg_plugin_devops en {py_file}"
                    )
            elif isinstance(node, ast.ImportFrom):
                mod_name = node.module or ""
                assert "jg_plugin_devops" not in mod_name, (
                    f"Core depende indebidamente de jg_plugin_devops en {py_file}"
                )
