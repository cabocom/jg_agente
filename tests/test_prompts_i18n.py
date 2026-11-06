# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Tests unitarios de internacionalización (i18n) para el catálogo de prompts."""

from __future__ import annotations

import pytest

from app.prompts.manager import (
    DEFAULT_CANONICAL_LOCALE,
    SUPPORTED_LOCALES,
    PromptManager,
    get_prompt_manager,
)


class TestPromptManager:
    """Verificación del comportamiento multilingüe de PromptManager."""

    @pytest.fixture
    def manager(self) -> PromptManager:
        return get_prompt_manager()

    def test_supported_locales_contains_five_languages(self) -> None:
        """Comprueba que los 5 idiomas obligatorios están soportados."""
        expected = {"es", "en", "fr", "de", "it"}
        assert set(SUPPORTED_LOCALES) == expected

    @pytest.mark.parametrize("loc", ["es", "en", "fr", "de", "it"])
    def test_load_all_core_templates_across_all_locales(
        self, manager: PromptManager, loc: str
    ) -> None:
        """Verifica que todas las plantillas canónicas existen y tienen contenido en cada idioma."""
        templates = ["system", "hitl_planning", "hitl_human", "intent_classifier", "guidance"]
        for tmpl in templates:
            content = manager.load_template(tmpl, locale=loc)
            assert content, f"Plantilla '{tmpl}' vacía o ausente para el locale '{loc}'"
            assert len(content) > 10

    def test_locale_fallback_deterministic(self, manager: PromptManager) -> None:
        """Verifica el fallback determinista al español ante locales desconocidos."""
        assert manager.resolve_locale("pt") == DEFAULT_CANONICAL_LOCALE
        assert manager.resolve_locale("zh") == DEFAULT_CANONICAL_LOCALE
        assert manager.resolve_locale(None) == DEFAULT_CANONICAL_LOCALE
        assert manager.resolve_locale("invalid-locale") == DEFAULT_CANONICAL_LOCALE

    def test_locale_priority_hierarchy(self, manager: PromptManager) -> None:
        """Verifica la jerarquía de prioridad: request > plugin > sistema > es."""
        assert (
            manager.resolve_locale(requested_locale="en", plugin_default="fr", system_default="de")
            == "en"
        )
        assert (
            manager.resolve_locale(requested_locale=None, plugin_default="fr", system_default="de")
            == "fr"
        )
        assert (
            manager.resolve_locale(requested_locale=None, plugin_default=None, system_default="de")
            == "de"
        )
        assert (
            manager.resolve_locale(requested_locale=None, plugin_default=None, system_default=None)
            == "es"
        )

    def test_locale_format_parsing(self, manager: PromptManager) -> None:
        """Soporta formatos compuestos tipo 'en_US', 'fr-FR', 'DE-AT'."""
        assert manager.resolve_locale("en_US") == "en"
        assert manager.resolve_locale("fr-FR") == "fr"
        assert manager.resolve_locale("de_DE") == "de"
        assert manager.resolve_locale("it-IT") == "it"
        assert manager.resolve_locale("es_ES") == "es"

    @pytest.mark.parametrize("loc", ["es", "en", "fr", "de", "it"])
    def test_render_hitl_planning_template_interpolation(
        self, manager: PromptManager, loc: str
    ) -> None:
        """Verifica que la plantilla de HITL interpola correctamente el catálogo de herramientas."""
        catalog_sample = "- docker_read: Inspecciona contenedores"
        rendered = manager.render("hitl_planning", locale=loc, tools_catalog_text=catalog_sample)
        assert catalog_sample in rendered
        assert "steps" in rendered

    @pytest.mark.parametrize("loc", ["es", "en", "fr", "de", "it"])
    def test_render_guidance_template_interpolation(self, manager: PromptManager, loc: str) -> None:
        """Verifica que la plantilla de realimentación multi-iteración interpola variables."""
        rendered = manager.render(
            "guidance",
            locale=loc,
            iteration=2,
            explanation="Test explanation",
            suggested_next_action="Run container",
            already_done_note="\nDone: ping",
        )
        assert "Test explanation" in rendered
        assert "Run container" in rendered
        assert "2" in rendered

    @pytest.mark.parametrize("loc", ["es", "en", "fr", "de", "it"])
    def test_system_prompt_verbosity_modes(self, manager: PromptManager, loc: str) -> None:
        """Verifica directivas de verbosidad concisa y detallada en cada idioma."""
        concise = manager.get_system_prompt(locale=loc, verbosity="concise")
        detailed = manager.get_system_prompt(locale=loc, verbosity="detailed")

        assert len(concise) > 20
        assert len(detailed) > 20
        assert concise != detailed

    @pytest.mark.parametrize("loc", ["es", "en", "fr", "de", "it"])
    def test_cognitive_meta_resolution(self, manager: PromptManager, loc: str) -> None:
        """Verifica metadatos de pasos cognitivos (título, acción, descripción) en cada idioma."""
        title, action, desc = manager.get_cognitive_meta(
            "act", locale=loc, count=2, summary="tool1, tool2"
        )
        assert title
        assert "tool1, tool2" in action
        assert "tool1, tool2" in desc

        title_d, action_d, desc_d = manager.get_cognitive_meta("conclude_direct", locale=loc)
        assert title_d
        assert action_d
        assert desc_d

    @pytest.mark.parametrize("loc", ["es", "en", "fr", "de", "it"])
    def test_mutative_keywords_and_greetings(self, manager: PromptManager, loc: str) -> None:
        """Verifica que las palabras clave de mutación y saludos existan para cada idioma."""
        mut_kws = manager.get_mutative_keywords(locale=loc)
        assert len(mut_kws) >= 10

        greetings = manager.get_pure_greetings(locale=loc)
        assert len(greetings) >= 5
