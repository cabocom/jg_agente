# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Constantes y catálogos estáticos de internacionalización para directivas de prompts."""

from __future__ import annotations

from app.prompts.cognitive_strings import COGNITIVE_STEP_STRINGS

SUPPORTED_LOCALES: tuple[str, ...] = ("es", "en", "fr", "de", "it")
DEFAULT_CANONICAL_LOCALE: str = "es"

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

__all__ = [
    "SUPPORTED_LOCALES",
    "DEFAULT_CANONICAL_LOCALE",
    "VERBOSITY_DIRECTIVES",
    "MUTATIVE_KEYWORDS",
    "PURE_GREETINGS",
    "COGNITIVE_STEP_STRINGS",
]
