# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Gestor de plugins (PluginManager) y ciclo de vida para jg_agente.

Responsable de descubrir, verificar dependencias, inicializar y registrar plugins
tanto locales como distribuidos vía entry_points en el CapabilityRegistry.
"""

import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Self

from app.core.plugin_loader import (
    PluginDependencyError,
    PluginLoadError,
    discover_entrypoints,
    discover_local_plugins,
    resolve_dependencies_and_order,
)
from app.core.registry import BootConflictError, CapabilityRegistry
from app.plugins.base import BasePlugin

logger = logging.getLogger("jg_agente.plugin_manager")

__all__ = [
    "PluginLoadError",
    "PluginDependencyError",
    "PluginManager",
    "discover_entrypoints",
    "discover_local_plugins",
    "resolve_dependencies_and_order",
]


class PluginManager:
    """Gestor de ciclo de vida, descubrimiento y resolución de dependencias de plugins."""

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        plugins_dir: Path | str | None = None,
        auto_register: bool = True,
        enabled_plugins: list[str] | set[str] | str | None = None,
    ) -> None:
        self.registry: CapabilityRegistry = (
            registry if registry is not None else CapabilityRegistry()
        )
        self.plugins_dir: Path | None = Path(plugins_dir) if plugins_dir is not None else None
        self.auto_register: bool = auto_register
        self.enabled_plugins: set[str] | None = self._parse_enabled_plugins(enabled_plugins)

        self._plugins: dict[str, BasePlugin] = {}
        self._load_order: list[str] = []
        self._is_started: bool = False

    @staticmethod
    def _parse_enabled_plugins(val: list[str] | set[str] | str | None) -> set[str] | None:
        """Normaliza la especificación de plugins habilitados a un conjunto en minúsculas."""
        if val is None:
            return None
        if isinstance(val, str):
            items = [x.strip().lower() for x in val.split(",") if x.strip()]
        else:
            items = [str(x).strip().lower() for x in val if str(x).strip()]
        if not items or "*" in items or "all" in items:
            return None
        return set(items)

    @property
    def loaded_plugins(self) -> dict[str, BasePlugin]:
        """Diccionario de plugins actualmente cargados indexados por su nombre único."""
        return dict(self._plugins)

    @property
    def load_order(self) -> list[str]:
        """Secuencia de plugins ordenada según resolución de dependencias."""
        return list(self._load_order)

    def discover_entrypoints(self, group: str = "jg_agente.plugins") -> list[type[BasePlugin]]:
        """Descubre clases de plugin registradas en el entorno mediante entry_points de Python."""
        import sys

        ep_fn = getattr(sys.modules[__name__], "entry_points", entry_points)
        return discover_entrypoints(group=group, entry_points_fn=ep_fn)

    def discover_local_plugins(self, directory: Path | str | None = None) -> list[type[BasePlugin]]:
        """Descubre plugins en carpetas locales buscando 'PLUGIN_CLASS' o subclases de BasePlugin."""
        target_dir = Path(directory) if directory is not None else self.plugins_dir
        return discover_local_plugins(target_dir)

    def register_plugin_instance(self, plugin: BasePlugin) -> None:
        """Registra e incorpora una instancia activa de plugin validando su compatibilidad."""
        if not isinstance(plugin, BasePlugin):
            raise PluginLoadError(
                f"El objeto provisto no es una instancia de BasePlugin: {type(plugin)}"
            )

        name = plugin.name
        if name in self._plugins:
            logger.warning("Plugin '%s' ya se encuentra registrado. Omitiendo duplicado.", name)
            return

        self._plugins[name] = plugin
        if self.auto_register:
            self.registry.register_plugin(plugin)

    def load_plugins(
        self,
        plugins_dir: Path | str | None = None,
        load_entrypoints: bool = True,
        load_local: bool = True,
        enabled_plugins: list[str] | set[str] | str | None = None,
    ) -> list[BasePlugin]:
        """Descubre, valida dependencias, ordena e inicializa todos los plugins del entorno."""
        discovered_classes: list[type[BasePlugin]] = []

        if load_local:
            discovered_classes.extend(self.discover_local_plugins(directory=plugins_dir))
        if load_entrypoints:
            discovered_classes.extend(self.discover_entrypoints())

        active_enabled = (
            self._parse_enabled_plugins(enabled_plugins)
            if enabled_plugins is not None
            else self.enabled_plugins
        )

        for plugin_cls in discovered_classes:
            try:
                instance = plugin_cls()
                meta = instance.get_plugin_metadata()
                plugin_name = meta.name.lower()
                module_name = plugin_cls.__module__.split(".")[0].lower()

                if (
                    active_enabled is not None
                    and plugin_name not in active_enabled
                    and module_name not in active_enabled
                ):
                    logger.info(
                        "Omitiendo plugin '%s' (módulo '%s'): no está en ENABLED_PLUGINS (%s)",
                        plugin_name,
                        module_name,
                        active_enabled,
                    )
                    continue

                self.register_plugin_instance(instance)
            except (BootConflictError, PluginDependencyError):
                raise
            except Exception as exc:
                logger.error("Fallo al instanciar plugin '%s': %s", plugin_cls, exc)
                raise PluginLoadError(f"Error instanciando {plugin_cls}: {exc}") from exc

        self._load_order = self._resolve_dependencies_and_order()
        return [self._plugins[name] for name in self._load_order]

    def _resolve_dependencies_and_order(self) -> list[str]:
        """Verifica dependencias requeridas y computa el orden topológico de inicialización."""
        return resolve_dependencies_and_order(self._plugins)

    async def startup(self) -> None:
        """Inicializa concurrentemente o en orden estricto de dependencias todos los plugins cargados."""
        if self._is_started:
            return

        if not self._load_order and self._plugins:
            self._load_order = self._resolve_dependencies_and_order()

        for name in self._load_order:
            plugin = self._plugins[name]
            logger.info("Inicializando plugin [%s] v%s...", name, plugin.version)
            await plugin.startup()

        self._is_started = True

    async def shutdown(self) -> None:
        """Apaga los plugins en orden inverso al de dependencias para liberar recursos limpiamente."""
        if not self._is_started:
            return

        for name in reversed(self._load_order):
            plugin = self._plugins[name]
            logger.info("Apagando plugin [%s]...", name)
            try:
                await plugin.shutdown()
            except Exception as exc:
                logger.error("Error durante shutdown de plugin '%s': %s", name, exc)

        self._is_started = False

    async def health_check(self) -> dict[str, Any]:
        """Consolida el estado de salud reportado por cada uno de los plugins activos."""
        statuses: dict[str, Any] = {}
        all_ok = True

        for name, plugin in self._plugins.items():
            try:
                health = await plugin.health_check()
                statuses[name] = health
                if health.get("status") != "ok":
                    all_ok = False
            except Exception as exc:
                statuses[name] = {"status": "error", "error": str(exc)}
                all_ok = False

        return {
            "status": "ok" if all_ok else "degraded",
            "plugins_count": len(self._plugins),
            "plugins": statuses,
        }

    async def __aenter__(self) -> Self:
        await self.startup()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.shutdown()
