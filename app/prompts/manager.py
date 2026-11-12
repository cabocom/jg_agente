# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Gestor de plantillas de prompts internacionalizadas (PromptManager).

Permite la resolución dinámica y determinista de directivas de sistema,
planificación HITL, clasificación de intenciones y realimentación iterativa
en castellano, inglés, francés, alemán e italiano (es, en, fr, de, it).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.prompts.i18n_constants import (
    COGNITIVE_STEP_STRINGS,
    DEFAULT_CANONICAL_LOCALE,
    MUTATIVE_KEYWORDS,
    PURE_GREETINGS,
    SUPPORTED_LOCALES,
    VERBOSITY_DIRECTIVES,
)

logger = logging.getLogger("jg_agente.prompts.manager")

__all__ = [
    "SUPPORTED_LOCALES",
    "DEFAULT_CANONICAL_LOCALE",
    "VERBOSITY_DIRECTIVES",
    "MUTATIVE_KEYWORDS",
    "PURE_GREETINGS",
    "COGNITIVE_STEP_STRINGS",
    "PromptManager",
    "get_prompt_manager",
]


class PromptManager:
    """Gestor centralizado de carga y renderizado de plantillas multilingües."""

    def __init__(self, templates_dir: Path | str | None = None) -> None:
        self.templates_dir = (
            Path(templates_dir) if templates_dir else Path(__file__).parent / "templates"
        )
        self._cache: dict[str, str] = {}

    def resolve_locale(
        self,
        requested_locale: str | None = None,
        plugin_default: str | None = None,
        system_default: str | None = None,
    ) -> str:
        """Resuelve el locale efectivo siguiendo la jerarquía de prioridad:

        1. requested_locale (procedente de AgentInput / request)
        2. plugin_default (declarado en PluginMetadata)
        3. system_default (declarado en Settings.DEFAULT_LOCALE)
        4. Fallback canónico: 'es'
        """
        for candidate in (requested_locale, plugin_default, system_default):
            if candidate and isinstance(candidate, str):
                norm = candidate.strip().lower()
                if len(norm) >= 2:
                    code = norm[:2]
                    if code in SUPPORTED_LOCALES:
                        return code
        return DEFAULT_CANONICAL_LOCALE

    def load_template(self, template_name: str, locale: str = DEFAULT_CANONICAL_LOCALE) -> str:
        """Carga el contenido de la plantilla solicitada con fallback seguro al español."""
        eff_locale = self.resolve_locale(locale)
        cache_key = f"{eff_locale}:{template_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        primary_path = self.templates_dir / eff_locale / f"{template_name}.txt"
        fallback_path = self.templates_dir / DEFAULT_CANONICAL_LOCALE / f"{template_name}.txt"

        content: str | None = None
        if primary_path.exists():
            try:
                content = primary_path.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning("Error al leer plantilla en %s: %s", primary_path, exc)

        if content is None and fallback_path.exists():
            try:
                content = fallback_path.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.error("Error al leer plantilla de fallback en %s: %s", fallback_path, exc)

        if content is None:
            content = ""

        self._cache[cache_key] = content
        return content

    def render(
        self, template_name: str, locale: str = DEFAULT_CANONICAL_LOCALE, **kwargs: Any
    ) -> str:
        """Renderiza una plantilla sustituyendo variables parametrizadas."""
        template_str = self.load_template(template_name, locale=locale)
        if not template_str:
            return ""
        try:
            return template_str.format(**kwargs)
        except KeyError as err:
            logger.warning("Falta variable %s al renderizar plantilla %s", err, template_name)
            return template_str
        except Exception as exc:
            logger.error("Fallo inesperado al renderizar plantilla %s: %s", template_name, exc)
            return template_str

    def get_system_prompt(
        self,
        locale: str = DEFAULT_CANONICAL_LOCALE,
        verbosity: str = "concise",
        base_prompt: str | None = None,
    ) -> str:
        """Construye el prompt de sistema completo con sus directivas de verbosidad."""
        eff_locale = self.resolve_locale(locale)
        content = (
            base_prompt.strip()
            if base_prompt and base_prompt.strip()
            else self.load_template("system", locale=eff_locale)
        )
        verb_norm = (verbosity or "concise").lower().strip()
        verb_dict = VERBOSITY_DIRECTIVES.get(
            eff_locale, VERBOSITY_DIRECTIVES[DEFAULT_CANONICAL_LOCALE]
        )
        directives = verb_dict.get(verb_norm, verb_dict.get("concise", ""))
        return f"{content}{directives}"

    def get_mutative_keywords(self, locale: str = DEFAULT_CANONICAL_LOCALE) -> tuple[str, ...]:
        """Retorna las palabras clave indicadoras de mutación en el idioma solicitado."""
        eff_locale = self.resolve_locale(locale)
        kws = set(MUTATIVE_KEYWORDS.get(eff_locale, ()))
        kws.update(MUTATIVE_KEYWORDS["en"])
        return tuple(kws)

    def get_pure_greetings(self, locale: str = DEFAULT_CANONICAL_LOCALE) -> set[str]:
        """Retorna el catálogo de saludos y cortesías puras en el idioma solicitado."""
        eff_locale = self.resolve_locale(locale)
        greetings = set(PURE_GREETINGS.get(eff_locale, ()))
        greetings.update(PURE_GREETINGS["en"])
        return greetings

    def get_cognitive_meta(
        self,
        step_type: str,
        locale: str = DEFAULT_CANONICAL_LOCALE,
        **kwargs: Any,
    ) -> tuple[str, str, str]:
        """Retorna (título, acción, descripción) de un CognitiveStepRecord adaptado al locale."""
        eff_locale = self.resolve_locale(locale)
        lang_dict = COGNITIVE_STEP_STRINGS.get(
            eff_locale, COGNITIVE_STEP_STRINGS[DEFAULT_CANONICAL_LOCALE]
        )
        meta = lang_dict.get(
            step_type, COGNITIVE_STEP_STRINGS[DEFAULT_CANONICAL_LOCALE].get(step_type, {})
        )

        title = str(meta.get("title", "Cognitive Step"))
        if step_type == "act":
            count = kwargs.get("count", 1)
            summary = kwargs.get("summary", "")
            if count > 1:
                action = meta.get("action_multi", "Action Plan: {summary}").format(
                    count=count, summary=summary
                )
                desc = meta.get("desc_multi", "Action plan formulated: {summary}").format(
                    count=count, summary=summary
                )
            else:
                action = meta.get("action_single", "Action Selection: {summary}").format(
                    summary=summary
                )
                desc = meta.get("desc_single", "Action determined: {summary}").format(
                    summary=summary
                )
        elif step_type == "plan":
            planner = kwargs.get("planner", "planner")
            action = meta.get("action", "Delegation to Planner: {planner}").format(planner=planner)
            desc = meta.get("description", "").format(planner=planner)
        else:
            action = str(meta.get("action", ""))
            desc = str(meta.get("description", ""))

        return title, action, desc


@lru_cache(maxsize=1)
def get_prompt_manager() -> PromptManager:
    """Singleton cacheado para la instancia global de PromptManager."""
    return PromptManager()
