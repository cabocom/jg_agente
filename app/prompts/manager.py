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

logger = logging.getLogger("jg_agente.prompts.manager")

SUPPORTED_LOCALES: tuple[str, ...] = ("es", "en", "fr", "de", "it")
DEFAULT_CANONICAL_LOCALE: str = "es"

# Diccionario de directivas de verbosidad por idioma
VERBOSITY_DIRECTIVES: dict[str, dict[str, str]] = {
    "es": {
        "concise": (
            "\n\nDIRECTIVAS DE RESPUESTA (CONCISO):\n"
            "- Sé directo, ejecutivo y conciso. Evita introducciones o florituras innecesarias.\n"
            "- Si respondes directamente sin herramientas, proporciona la información esencial en 1 a 3 frases claras.\n"
            "- No hagas meta-comentarios sobre tu propio catálogo interno ni sobre las partes de la pregunta del usuario."
        ),
        "detailed": (
            "\n\nDIRECTIVAS DE RESPUESTA (DETALLADO):\n"
            "- Proporciona explicaciones minuciosas y detalladas con análisis exhaustivo."
        ),
    },
    "en": {
        "concise": (
            "\n\nRESPONSE DIRECTIVES (CONCISE):\n"
            "- Be direct, executive, and concise. Avoid unnecessary introductions or pleasantries.\n"
            "- If answering directly without tools, deliver the essential information in 1 to 3 clear sentences.\n"
            "- Do not make meta-commentary about your internal tool catalog or about parsing the user request."
        ),
        "detailed": (
            "\n\nRESPONSE DIRECTIVES (DETAILED):\n"
            "- Provide thorough, detailed explanations with in-depth operational analysis."
        ),
    },
    "fr": {
        "concise": (
            "\n\nDIRECTIVES DE RÉPONSE (CONCIS):\n"
            "- Soyez direct, exécutif et concis. Évitez les formules de politesse ou introductions superflues.\n"
            "- En cas de réponse directe sans outils, fournissez les informations essentielles en 1 à 3 phrases claires.\n"
            "- Ne faites aucun méta-commentaire sur votre catalogue interne d'outils."
        ),
        "detailed": (
            "\n\nDIRECTIVES DE RÉPONSE (DÉTAILLÉ):\n"
            "- Fournissez des explications complètes et détaillées avec une analyse opérationnelle approfondie."
        ),
    },
    "de": {
        "concise": (
            "\n\nANTWORT-RICHTLINIEN (PRÄGNANT):\n"
            "- Seien Sie direkt, sachlich und präzise. Vermeiden Sie überflüssige Einleitungen.\n"
            "- Geben Sie bei direkten Antworten ohne Werkzeuge die Kerninformationen in 1 bis 3 klaren Sätzen wieder.\n"
            "- Verzichten Sie auf Meta-Kommentare über Ihren internen Werkzeugkatalog."
        ),
        "detailed": (
            "\n\nANTWORT-RICHTLINIEN (DETAILLIERT):\n"
            "- Liefern Sie gründliche, detaillierte Erklärungen mit fundierter technischer Analyse."
        ),
    },
    "it": {
        "concise": (
            "\n\nDIRETTIVE DI RISPOSTA (CONCISO):\n"
            "- Sii diretto, operativo e conciso. Evita introduzioni o convenevoli non necessari.\n"
            "- Se rispondi direttamente senza strumenti, fornisci le informazioni essenziali in 1-3 frasi chiare.\n"
            "- Non inserire meta-commenti sul catalogo interno di strumenti."
        ),
        "detailed": (
            "\n\nDIRETTIVE DI RISPOSTA (DETTAGLIATO):\n"
            "- Fornisci spiegazioni approfondite e dettagliate con analisi tecnica accurata."
        ),
    },
}

# Palabras clave mutativas multilingües
MUTATIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "es": (
        "crea",
        "crear",
        "despliega",
        "desplegar",
        "lanza",
        "lanzar",
        "reinicia",
        "reiniciar",
        "elimina",
        "eliminar",
        "borra",
        "borrar",
        "detén",
        "detener",
        "para",
        "parar",
        "modifica",
        "modificar",
        "actualiza",
        "actualizar",
        "escribe",
        "escribir",
    ),
    "en": (
        "create",
        "deploy",
        "run",
        "launch",
        "restart",
        "reboot",
        "delete",
        "remove",
        "stop",
        "halt",
        "kill",
        "modify",
        "update",
        "write",
        "patch",
        "mutate",
    ),
    "fr": (
        "crée",
        "créer",
        "déploie",
        "déployer",
        "lance",
        "lancer",
        "redémarre",
        "redémarrer",
        "supprime",
        "supprimer",
        "efface",
        "effacer",
        "arrête",
        "arrêter",
        "stoppe",
        "stopper",
        "modifie",
        "modifier",
        "mets à jour",
        "mettre à jour",
    ),
    "de": (
        "erstelle",
        "erstellen",
        "bereitstellen",
        "starte",
        "starten",
        "neu starten",
        "neustarten",
        "lösche",
        "löschen",
        "entferne",
        "entfernen",
        "stoppe",
        "stoppen",
        "anhalten",
        "ändere",
        "ändern",
        "aktualisiere",
        "aktualisieren",
    ),
    "it": (
        "crea",
        "creare",
        "distribuisci",
        "distribuire",
        "lancia",
        "lanciare",
        "riavvia",
        "riavviare",
        "elimina",
        "eliminare",
        "cancella",
        "cancellare",
        "ferma",
        "fermare",
        "arresta",
        "arrestare",
        "modifica",
        "modificare",
        "aggiorna",
        "aggiornare",
    ),
}

# Fórmulas de cortesía puras por idioma
PURE_GREETINGS: dict[str, set[str]] = {
    "es": {
        "hola",
        "saludos",
        "buenos días",
        "buenas tardes",
        "buenas noches",
        "hey",
        "adiós",
        "chao",
        "hasta luego",
        "gracias",
    },
    "en": {
        "hello",
        "hi",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "goodbye",
        "bye",
        "thanks",
        "thank you",
    },
    "fr": {
        "bonjour",
        "salut",
        "bonsoir",
        "au revoir",
        "merci",
        "merci beaucoup",
    },
    "de": {
        "hallo",
        "guten morgen",
        "guten tag",
        "guten abend",
        "tschüss",
        "auf wiedersehen",
        "danke",
    },
    "it": {
        "ciao",
        "buongiorno",
        "buonasera",
        "salve",
        "arrivederci",
        "grazie",
        "grazie mille",
    },
}

# Títulos de etapas cognitivas
COGNITIVE_STEP_STRINGS: dict[str, dict[str, dict[str, str]]] = {
    "es": {
        "conclude_dedup": {
            "title": "Razonamiento y Conclusión Reflexiva",
            "action": "Resolución sin duplicación de acciones",
            "description": "El agente detectó que las herramientas propuestas ya se ejecutaron con idénticos parámetros, evitando llamadas redundantes.",
        },
        "act": {
            "title": "Razonamiento e Interpretación Cognitiva",
            "action_multi": "Plan de Acción ({count} etapas): {summary}",
            "action_single": "Selección de Acción: {summary}",
            "desc_multi": "El agente formuló un plan de acción de {count} etapas: {summary}.",
            "desc_single": "El agente interpretó la solicitud y determinó ejecutar: {summary}.",
        },
        "plan": {
            "title": "Razonamiento y Planificación Cognitiva",
            "action": "Delegación a Planificador: {planner}",
            "description": "Solicitud operativa compleja detectada. El agente delega en el motor '{planner}' para formular un plan de pasos secuenciales.",
        },
        "conclude_direct": {
            "title": "Razonamiento y Respuesta Directa",
            "action": "Resolución Conversacional",
            "description": "El agente analizó la consulta y determinó que no requiere invocar herramientas operativas, procediendo a responder directamente.",
        },
    },
    "en": {
        "conclude_dedup": {
            "title": "Reasoning & Reflective Conclusion",
            "action": "Resolution without duplicate actions",
            "description": "The agent detected that the proposed tools were already executed with identical arguments, avoiding redundant invocations.",
        },
        "act": {
            "title": "Cognitive Reasoning & Interpretation",
            "action_multi": "Action Plan ({count} steps): {summary}",
            "action_single": "Action Selection: {summary}",
            "desc_multi": "The agent formulated an action plan with {count} steps: {summary}.",
            "desc_single": "The agent interpreted the request and decided to execute: {summary}.",
        },
        "plan": {
            "title": "Cognitive Reasoning & Planning",
            "action": "Delegation to Planner: {planner}",
            "description": "Complex operational request detected. The agent delegates to the '{planner}' engine to construct a sequential action plan.",
        },
        "conclude_direct": {
            "title": "Reasoning & Direct Response",
            "action": "Conversational Resolution",
            "description": "The agent analyzed the query and determined it does not require operational tools, responding directly.",
        },
    },
    "fr": {
        "conclude_dedup": {
            "title": "Raisonnement et Conclusion Réflexive",
            "action": "Résolution sans actions redondantes",
            "description": "L'agent a détecté que les outils proposés ont déjà été exécutés avec des arguments identiques, évitant les invocations superflues.",
        },
        "act": {
            "title": "Raisonnement et Interprétation Cognitive",
            "action_multi": "Plan d'Action ({count} étapes) : {summary}",
            "action_single": "Sélection d'Action : {summary}",
            "desc_multi": "L'agent a formulé un plan d'action en {count} étapes : {summary}.",
            "desc_single": "L'agent a interprété la requête et a décidé d'exécuter : {summary}.",
        },
        "plan": {
            "title": "Raisonnement et Planification Cognitive",
            "action": "Délégation au Planificateur : {planner}",
            "description": "Requête opérationnelle complexe détectée. L'agent délègue au moteur '{planner}' pour construire un plan d'étapes séquentielles.",
        },
        "conclude_direct": {
            "title": "Raisonnement et Réponse Directe",
            "action": "Résolution Conversationnelle",
            "description": "L'agent a analysé la demande et déterminé qu'aucun outil opérationnel n'est requis, répondant directement.",
        },
    },
    "de": {
        "conclude_dedup": {
            "title": "Kognitive Schlussfolgerung & Reflexion",
            "action": "Auflösung ohne redundante Aktionen",
            "description": "Der Agent hat erkannt, dass die vorgeschlagenen Werkzeuge bereits mit identischen Parametern ausgeführt wurden.",
        },
        "act": {
            "title": "Kognitive Interpretation & Handlungsplanung",
            "action_multi": "Aktionsplan ({count} Stufen): {summary}",
            "action_single": "Aktionsauswahl: {summary}",
            "desc_multi": "Der Agent hat einen Aktionsplan mit {count} Schritten formuliert: {summary}.",
            "desc_single": "Der Agent hat die Anfrage interpretiert und beschlossen auszuführen: {summary}.",
        },
        "plan": {
            "title": "Kognitive Planung & Delegation",
            "action": "Delegation an Planer: {planner}",
            "description": "Komplexe betriebliche Anfrage erkannt. Der Agent delegiert an die Komponente '{planner}' zur Erstellung eines Ablaufplans.",
        },
        "conclude_direct": {
            "title": "Kognitive Analyse & Direkte Antwort",
            "action": "Konversationelle Auflösung",
            "description": "Der Agent hat die Anfrage analysiert und festgestellt, dass keine operativen Werkzeuge erforderlich sind.",
        },
    },
    "it": {
        "conclude_dedup": {
            "title": "Ragionamento e Conclusione Riflessiva",
            "action": "Risoluzione senza azioni duplicate",
            "description": "L'agente ha rilevato che gli strumenti proposti sono già stati eseguiti con argomenti identici, evitando chiamate ridondanti.",
        },
        "act": {
            "title": "Ragionamento e Interpretazione Cognitiva",
            "action_multi": "Piano d'Azione ({count} fasi): {summary}",
            "action_single": "Selezione Azione: {summary}",
            "desc_multi": "L'agente ha formulato un piano d'azione di {count} fasi: {summary}.",
            "desc_single": "L'agente ha interpretato la richiesta e ha deciso di eseguire: {summary}.",
        },
        "plan": {
            "title": "Ragionamento e Pianificazione Cognitiva",
            "action": "Delega al Pianificatore: {planner}",
            "description": "Richiesta operativa complessa rilevata. L'agente delega al motore '{planner}' per formulare un piano sequenziale.",
        },
        "conclude_direct": {
            "title": "Ragionamento e Risposta Diretta",
            "action": "Risoluzione Conversazionale",
            "description": "L'agente ha analizzato la richiesta e ha determinato che non richiede strumenti operativi, procedendo direttamente.",
        },
    },
}


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
                # Extraer código de 2 letras si viene en formato 'es_ES' o 'en-US'
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
        # Combinar las del idioma objetivo con las universales en inglés
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
