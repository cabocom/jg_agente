# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Catálogos de cadenas internacionalizadas para saltos cognitivos en trazas."""

from __future__ import annotations

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
            "description": "L'agent a analysé la demande et déterminé qu'aucun outil opérationnel n'est requis, répondant directamente.",
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

__all__ = ["COGNITIVE_STEP_STRINGS"]
