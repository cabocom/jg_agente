# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez <contacto@javiergalvez.com>
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Comprobación de integridad y validación en tiempo de arranque (Boot) de jg_agente.

Asegura que el conjunto de plugins, motores y herramientas registradas en el
CapabilityRegistry cumplan los requerimientos esenciales del perfil del agente
antes de inicializar FastAPI y aceptar tráfico de ejecución.
"""

import logging
from collections.abc import Sequence

from app.core.config import Settings
from app.core.config import settings as default_settings
from app.core.plugin_manager import PluginManager
from app.core.registry import CapabilityRegistry

logger = logging.getLogger("jg_agente.boot")


class BootIntegrityError(Exception):
    """Excepción lanzada cuando faltan capacidades esenciales o se detectan inconsistencias en boot."""

    pass


def validate_boot_capabilities(
    registry: CapabilityRegistry,
    required_plugins: Sequence[str] | None = None,
    required_tools: Sequence[str] | None = None,
    require_planner: bool = False,
    require_observer: bool = False,
    require_verifier: bool = False,
) -> None:
    """Valida la coherencia e integridad de capacidades registradas contra los requerimientos del perfil.

    Lanza BootIntegrityError de forma explícita si algún componente esencial falta
    o si las herramientas registradas presentan inconsistencias funcionales.
    """
    # 1. Validación de plugins requeridos
    if required_plugins:
        available_plugins = {p.name for p in registry.list_plugins()}
        missing_plugins = [p for p in required_plugins if p not in available_plugins]
        if missing_plugins:
            msg = (
                f"Fallo de integridad en boot: Los siguientes plugins esenciales no se encuentran registrados: "
                f"{', '.join(missing_plugins)}."
            )
            logger.error(msg)
            raise BootIntegrityError(msg)

    # 2. Validación de herramientas requeridas
    if required_tools:
        missing_tools = [t for t in required_tools if not registry.has_tool(t)]
        if missing_tools:
            msg = (
                f"Fallo de integridad en boot: Las siguientes herramientas esenciales no se encuentran registradas: "
                f"{', '.join(missing_tools)}."
            )
            logger.error(msg)
            raise BootIntegrityError(msg)

    # 3. Validación de motores cognitivos obligatorios
    if require_planner and registry.get_planner() is None:
        msg = (
            "Fallo de integridad en boot: El perfil del agente exige un PlannerEngine registrado, "
            "pero no se encontró ningún motor planificador activo."
        )
        logger.error(msg)
        raise BootIntegrityError(msg)

    if require_observer and registry.get_observer() is None:
        msg = (
            "Fallo de integridad en boot: El perfil del agente exige un ObserverEngine registrado, "
            "pero no se encontró ningún motor observador activo."
        )
        logger.error(msg)
        raise BootIntegrityError(msg)

    if require_verifier and registry.get_verifier() is None:
        msg = (
            "Fallo de integridad en boot: El perfil del agente exige un VerifierEngine registrado, "
            "pero no se encontró ningún motor verificador activo."
        )
        logger.error(msg)
        raise BootIntegrityError(msg)

    # 4. Validación de integridad interna de herramientas
    for tool in registry.list_tools():
        if not callable(tool.func):
            msg = f"Fallo de integridad en boot: La herramienta '{tool.name}' no define una función ejecutable callable."
            logger.error(msg)
            raise BootIntegrityError(msg)
        if not tool.category.strip():
            msg = f"Fallo de integridad en boot: La herramienta '{tool.name}' no tiene categoría asignada."
            logger.error(msg)
            raise BootIntegrityError(msg)

    logger.info(
        "Verificación de integridad en boot completada con éxito. "
        "Capacidades: %d tools, %d engines, %d plugins.",
        len(registry.list_tools()),
        len(registry.list_engines()),
        len(registry.list_plugins()),
    )


def init_agent_capabilities(
    cfg: Settings | None = None,
    registry: CapabilityRegistry | None = None,
    plugin_manager: PluginManager | None = None,
) -> tuple[CapabilityRegistry, PluginManager]:
    """Orquesta la inicialización, carga de plugins y validación de integridad en el arranque del agente."""
    active_settings = cfg or default_settings
    reg = registry if registry is not None else CapabilityRegistry()
    pm = (
        plugin_manager
        if plugin_manager is not None
        else PluginManager(
            registry=reg,
            plugins_dir=active_settings.PLUGINS_DIR,
            enabled_plugins=active_settings.ENABLED_PLUGINS,
        )
    )

    logger.info("Cargando y autodescubriendo plugins para jg_agente...")
    pm.load_plugins()

    logger.info("Validando coherencia de capacidades contra el perfil configurado...")
    validate_boot_capabilities(
        registry=reg,
        required_plugins=active_settings.REQUIRED_PLUGINS,
        required_tools=active_settings.REQUIRED_TOOLS,
        require_planner=active_settings.REQUIRE_PLANNER,
        require_observer=active_settings.REQUIRE_OBSERVER,
        require_verifier=active_settings.REQUIRE_VERIFIER,
    )

    return reg, pm
