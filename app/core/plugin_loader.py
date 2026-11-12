# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Descubrimiento de plugins y resolución de dependencias topológicas."""

import importlib
import inspect
import logging
import pkgutil
import sys
from collections import deque
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from app.plugins.base import BasePlugin

logger = logging.getLogger("jg_agente.plugin_manager")


class PluginLoadError(Exception):
    """Excepción lanzada cuando ocurre un fallo al descubrir, importar o cargar un plugin."""

    pass


class PluginDependencyError(PluginLoadError):
    """Excepción lanzada cuando un plugin declara dependencias ausentes o circulares."""

    pass


def discover_entrypoints(
    group: str = "jg_agente.plugins",
    entry_points_fn: Callable[..., Any] | None = None,
) -> list[type[BasePlugin]]:
    """Descubre clases de plugin registradas en el entorno mediante entry_points de Python."""
    discovered: list[type[BasePlugin]] = []
    ep_func = entry_points_fn or entry_points
    try:
        eps = ep_func(group=group)
    except Exception as exc:
        logger.warning("Error al consultar entry_points para el grupo '%s': %s", group, exc)
        return discovered

    for ep in eps:
        try:
            plugin_cls = ep.load()
            if not (inspect.isclass(plugin_cls) and issubclass(plugin_cls, BasePlugin)):
                raise PluginLoadError(
                    f"El entry_point '{ep.name}' no referencia una subclase válida de BasePlugin: {plugin_cls}"
                )
            discovered.append(plugin_cls)
            logger.info("Plugin descubierto vía entry_point [%s]: %s", ep.name, plugin_cls)
        except Exception as exc:
            logger.error("Error al cargar entry_point '%s': %s", ep.name, exc)
            raise PluginLoadError(f"Fallo al cargar entry_point '{ep.name}': {exc}") from exc

    return discovered


def _find_plugin_class_in_module(module_name: str, is_pkg: bool) -> type[BasePlugin] | None:
    """Intenta localizar la clase BasePlugin en un módulo o submódulo."""
    if is_pkg:
        try:
            submodule = importlib.import_module(f"{module_name}.plugin")
            if hasattr(submodule, "PLUGIN_CLASS"):
                candidate = submodule.PLUGIN_CLASS
                if inspect.isclass(candidate) and issubclass(candidate, BasePlugin):
                    return candidate
        except ModuleNotFoundError:
            pass
        except Exception as exc:
            logger.error("Error al importar %s.plugin: %s", module_name, exc)
            raise PluginLoadError(f"Fallo al importar '{module_name}.plugin': {exc}") from exc

    try:
        mod = importlib.import_module(module_name)
        if hasattr(mod, "PLUGIN_CLASS"):
            candidate = mod.PLUGIN_CLASS
            if inspect.isclass(candidate) and issubclass(candidate, BasePlugin):
                return candidate
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                return obj
    except Exception as exc:
        logger.error("Error al importar módulo local '%s': %s", module_name, exc)
        raise PluginLoadError(f"Fallo al importar módulo de plugin '{module_name}': {exc}") from exc

    return None


def discover_local_plugins(directory: Path | str | None = None) -> list[type[BasePlugin]]:
    """Descubre plugins en carpetas locales buscando 'PLUGIN_CLASS' o subclases de BasePlugin."""
    if directory is None:
        return []
    target_dir = Path(directory)
    if not target_dir.exists():
        return []

    target_dir_str = str(target_dir.resolve())
    if target_dir_str not in sys.path:
        sys.path.insert(0, target_dir_str)

    discovered: list[type[BasePlugin]] = []
    for _finder, module_name, is_pkg in pkgutil.iter_modules([target_dir_str]):
        candidate_cls = _find_plugin_class_in_module(module_name, is_pkg)
        if candidate_cls is not None:
            if not (inspect.isclass(candidate_cls) and issubclass(candidate_cls, BasePlugin)):
                raise PluginLoadError(
                    f"El componente '{module_name}' no exporta una subclase válida de BasePlugin."
                )
            discovered.append(candidate_cls)
            logger.info("Plugin local descubierto en '%s': %s", module_name, candidate_cls)

    return discovered


def resolve_dependencies_and_order(plugins: dict[str, BasePlugin]) -> list[str]:
    """Verifica dependencias requeridas y computa el orden topológico de inicialización (Kahn)."""
    in_degree: dict[str, int] = dict.fromkeys(plugins, 0)
    adjacency: dict[str, list[str]] = {name: [] for name in plugins}

    for name, plugin in plugins.items():
        metadata = plugin.get_plugin_metadata()
        for dep in metadata.dependencies:
            if dep not in plugins:
                raise PluginDependencyError(
                    f"Dependencia insatisfecha: El plugin '{name}' requiere el plugin '{dep}', "
                    "pero no se encuentra disponible o activo en el entorno."
                )
            adjacency[dep].append(name)
            in_degree[name] += 1

    queue: deque[str] = deque([name for name, deg in in_degree.items() if deg == 0])
    ordered: list[str] = []

    while queue:
        node = queue.popleft()
        ordered.append(node)
        for neighbor in adjacency[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(ordered) != len(plugins):
        unresolved = [name for name, deg in in_degree.items() if deg > 0]
        raise PluginDependencyError(
            f"Dependencia circular detectada entre los plugins: {', '.join(unresolved)}"
        )

    return ordered
