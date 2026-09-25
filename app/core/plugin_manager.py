"""Gestor de plugins (PluginManager) y autodescubrimiento para jg_agente.

Responsable de descubrir, verificar dependencias, inicializar y registrar plugins
tanto locales como distribuidos vía entry_points en el CapabilityRegistry.
"""

import importlib
import inspect
import logging
import pkgutil
import sys
from collections import deque
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Self

from app.core.registry import BootConflictError, CapabilityRegistry
from app.plugins.base import BasePlugin

logger = logging.getLogger("jg_agente.plugin_manager")


class PluginLoadError(Exception):
    """Excepción lanzada cuando ocurre un fallo al descubrir, importar o cargar un plugin."""

    pass


class PluginDependencyError(PluginLoadError):
    """Excepción lanzada cuando un plugin declara dependencias ausentes o circulares."""

    pass


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

    # --- Descubrimiento ---

    def discover_entrypoints(self, group: str = "jg_agente.plugins") -> list[type[BasePlugin]]:
        """Descubre clases de plugin registradas en el entorno mediante entry_points de Python."""
        discovered: list[type[BasePlugin]] = []
        try:
            eps = entry_points(group=group)
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

    def discover_local_plugins(self, directory: Path | str | None = None) -> list[type[BasePlugin]]:
        """Descubre plugins en carpetas locales buscando 'PLUGIN_CLASS' o subclases de BasePlugin."""
        target_dir = Path(directory) if directory is not None else self.plugins_dir
        discovered: list[type[BasePlugin]] = []

        if target_dir is None or not target_dir.exists():
            return discovered

        target_dir_str = str(target_dir.resolve())
        if target_dir_str not in sys.path:
            sys.path.insert(0, target_dir_str)

        for _finder, module_name, is_pkg in pkgutil.iter_modules([target_dir_str]):
            candidate_cls: type[BasePlugin] | None = None

            # 1. Intentar cargar subpaquete {module_name}.plugin
            if is_pkg:
                try:
                    submodule = importlib.import_module(f"{module_name}.plugin")
                    if hasattr(submodule, "PLUGIN_CLASS"):
                        cls_candidate = submodule.PLUGIN_CLASS
                        if inspect.isclass(cls_candidate) and issubclass(cls_candidate, BasePlugin):
                            candidate_cls = cls_candidate
                except ModuleNotFoundError:
                    pass
                except Exception as exc:
                    logger.error("Error al importar %s.plugin: %s", module_name, exc)
                    raise PluginLoadError(
                        f"Fallo al importar '{module_name}.plugin': {exc}"
                    ) from exc

            # 2. Si no se encontró en .plugin, intentar cargar directamente el módulo raíz
            if candidate_cls is None:
                try:
                    mod = importlib.import_module(module_name)
                    if hasattr(mod, "PLUGIN_CLASS"):
                        cls_candidate = mod.PLUGIN_CLASS
                        if inspect.isclass(cls_candidate) and issubclass(cls_candidate, BasePlugin):
                            candidate_cls = cls_candidate
                    else:
                        # Inspeccionar clases exportadas en el módulo
                        for _, obj in inspect.getmembers(mod, inspect.isclass):
                            if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                                candidate_cls = obj
                                break
                except Exception as exc:
                    logger.error("Error al importar módulo local '%s': %s", module_name, exc)
                    raise PluginLoadError(
                        f"Fallo al importar módulo de plugin '{module_name}': {exc}"
                    ) from exc

            if candidate_cls is not None:
                if not (inspect.isclass(candidate_cls) and issubclass(candidate_cls, BasePlugin)):
                    raise PluginLoadError(
                        f"El componente '{module_name}' no exporta una subclase válida de BasePlugin."
                    )
                discovered.append(candidate_cls)
                logger.info("Plugin local descubierto en '%s': %s", module_name, candidate_cls)

        return discovered

    # --- Carga y Registro ---

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

        # Resolver orden topológico de dependencias
        self._load_order = self._resolve_dependencies_and_order()
        return [self._plugins[name] for name in self._load_order]

    # --- Validación de Dependencias y Ordenamiento Topológico ---

    def _resolve_dependencies_and_order(self) -> list[str]:
        """Verifica dependencias requeridas y computa el orden topológico de inicialización."""
        in_degree: dict[str, int] = dict.fromkeys(self._plugins, 0)
        adjacency: dict[str, list[str]] = {name: [] for name in self._plugins}

        for name, plugin in self._plugins.items():
            metadata = plugin.get_plugin_metadata()
            for dep in metadata.dependencies:
                if dep not in self._plugins:
                    raise PluginDependencyError(
                        f"Dependencia insatisfecha: El plugin '{name}' requiere el plugin '{dep}', "
                        "pero no se encuentra disponible o activo en el entorno."
                    )
                # dep debe inicializarse antes de name -> arco: dep -> name
                adjacency[dep].append(name)
                in_degree[name] += 1

        # Algoritmo de Kahn para ordenación topológica
        queue: deque[str] = deque([name for name, deg in in_degree.items() if deg == 0])
        ordered: list[str] = []

        while queue:
            node = queue.popleft()
            ordered.append(node)

            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(ordered) != len(self._plugins):
            unresolved = [name for name, deg in in_degree.items() if deg > 0]
            raise PluginDependencyError(
                f"Dependencia circular detectada entre los plugins: {', '.join(unresolved)}"
            )

        return ordered

    # --- Ciclo de Vida Asíncrono ---

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

        # Apagado en orden inverso
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
