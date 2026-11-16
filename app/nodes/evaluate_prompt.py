# ==============================================================================
# Part of the javiergalvez-ia ecosystem.
# Author: Javier Gálvez
# License: GNU AGPLv3 (or Commercial Enterprise License where applicable)
# Project URL: https://javiergalvez.com | https://gitlab.com/javiergalvez-ia/jg_agente
# ==============================================================================

"""Construcción de prompts y payloads para la evaluación semántica (evaluate)."""

import json
from typing import Any


def _preview_output(raw_out: Any) -> str:
    """Acorta la salida de una herramienta si supera 1500 caracteres."""
    s = str(raw_out or "")
    if len(s) <= 1500:
        return s
    return s[:750] + "\n... [preview truncado] ...\n" + s[-750:]


def build_evaluate_system_prompt(verbosity: str = "concise") -> str:
    """Construye el System Prompt evaluador con Capability-Awareness y directivas de estilo."""
    verb = (verbosity or "concise").lower().strip()
    if verb == "concise":
        style_instructions = (
            "DIRECTIVAS ESTRICTAS DE ESTILO Y CONCISIÓN (OBLIGATORIO):\n"
            "- Sé DIRECTO, EJECUTIVO y CONCISO (máximo 1 o 2 frases breves).\n"
            "- PROHIBIDO TERMINANTEMENTE hablar en tercera persona sobre las herramientas o su ejecución "
            "(ej. NUNCA digas 'La respuesta del tool X indica...', 'El tool X devolvió...', 'Se cumplió la solicitud del usuario').\n"
            "- PROHIBIDO hacer meta-comentarios sobre la formulación de la pregunta del usuario "
            "(ej. NO digas 'lo que responde a la primera parte del objetivo del usuario', 'según la solicitud', etc.).\n"
            "- PROHIBIDO hablar de procesos internos o catálogos abstractos con rodeos "
            "(ej. en lugar de 'En el catálogo de herramientas disponible no existe ninguna herramienta para...', "
            "sé directo: 'Todos los contenedores están en ejecución. No está disponible la herramienta para inspeccionar logs.').\n"
            "- Comunica el estado real, los datos sustantivos y las conclusiones operativas de manera tajante, "
            "directamente dirigida al usuario (ej. 'El clima actual en Alcobendas es de 20°C con cielo despejado').\n"
        )
    elif verb == "detailed":
        style_instructions = (
            "DIRECTIVAS DE ESTILO:\n"
            "- Proporciona un desglose detallado y paso a paso de los hallazgos técnicos para el operador.\n"
            "- PROHIBIDO hablar en tercera persona sobre las herramientas (NUNCA 'La respuesta del tool...'). "
            "Responde directamente con los datos y hechos averiguados.\n"
        )
    else:
        style_instructions = (
            "DIRECTIVAS DE ESTILO:\n"
            "- Explica con claridad el estado del objetivo sin redundancias innecesarias.\n"
            "- PROHIBIDO hablar en tercera persona sobre las herramientas. Responde directamente con los datos averiguados.\n"
        )

    return (
        "Eres el Evaluador Cognitivo y Síntesis de Objetivos de un sistema de agentes autónomos.\n"
        "Tu misión es evaluar si la evidencia técnica recopilada responde a la solicitud del usuario "
        "y generar en el campo 'explanation' la respuesta final en lenguaje natural que leerá el usuario humano.\n\n"
        f"{style_instructions}\n"
        "INSTRUCCIONES PARA 'explanation' SEGÚN 'goal_status':\n"
        "1. 'satisfied': Si la información técnica obtenida responde a la solicitud del usuario (por ejemplo, si solicitó logs, listados, métricas, estado de infraestructura o lectura de datos y las observaciones ya los contienen) "
        "O si la solicitud es conversacional, explicativa, de opinión, argumentativa o de conocimiento general (ej. preguntas sobre por qué un equipo es el mejor, reflexiones, resúmenes o datos temáticos) y ya se ejecutó al menos una herramienta de consulta o se dispone de contexto suficiente. "
        "En 'explanation', DEBES responder DIRECTAMENTE al usuario comunicando los datos concretos obtenidos, argumentando con solidez y citando fuentes si aplica "
        "(ej. si preguntó por qué el Real Madrid es el mejor, argumenta con pasión y rigor en pasado, presente y futuro citando las fuentes consultadas; si preguntó por el clima, indica el clima exacto y temperatura). "
        "PROHIBIDO TERMINANTEMENTE actuar como un auditor externo o hablar de las herramientas en tercera persona "
        "(NUNCA digas: 'La respuesta del tool indica...', 'El tool devolvió...', 'Cumpliendo la solicitud del usuario', etc.). "
        "Habla de tú a tú al usuario con la información final solicitada.\n"
        "2. 'needs_more_info': ÚNICAMENTE si para cumplir una tarea puramente operativa/técnica se requiere de forma indispensable ejecutar una herramienta adicional o una nueva operación con parámetros complementarios DISTINTOS a los ya ejecutados "
        "que SÍ está disponible en el catálogo de herramientas registradas. PROHIBIDO marcar 'needs_more_info' en consultas conversacionales, de opinión o argumentativas donde ya se consultó una herramienta de búsqueda o RAG. "
        "Explica qué dato concreto falta y qué comando/parámetros específicos se deben ejecutar a continuación (NO repitas un comando que ya esté en 'executed_steps').\n"
        "3. 'blocked_missing_capability': Si detectas un problema o si el usuario solicitó investigar algo "
        "pero la herramienta requerida NO EXISTE en el catálogo de herramientas registradas. "
        "Indica brevemente qué hallazgo real hay y qué herramienta o capacidad específica falta.\n"
        "4. 'failed': Si ocurrió un error irrecuperable que imposibilita continuar. Explica el motivo de forma clara.\n\n"
        "DEBES RESPONDER EXCLUSIVAMENTE CON UN OBJETO JSON con la siguiente estructura:\n"
        "{\n"
        '  "goal_status": "satisfied" | "needs_more_info" | "blocked_missing_capability" | "failed",\n'
        '  "explanation": "Respuesta directa y sustantiva en lenguaje natural para el usuario con los datos reales obtenidos, sin meta-comentarios sobre herramientas",\n'
        '  "missing_capabilities": ["nombre_herramienta_faltante"],\n'
        '  "suggested_next_action": "nombre_herramienta_sugerida_si_aplica_o_null"\n'
        "}"
    )


def build_evaluate_user_payload(
    prompt: str,
    iteration: int,
    available_tools: list[dict[str, Any]],
    exec_records: list[Any],
    tool_messages: list[str],
    error_summaries: list[str],
) -> str:
    """Construye el contenido JSON formateado para el mensaje del usuario al modelo evaluador."""
    user_payload = {
        "user_goal": prompt,
        "iteration": iteration,
        "available_tools": available_tools,
        "executed_steps": [
            {
                "tool": r.tool_name,
                "args": getattr(r, "tool_args", {}),
                "status": r.status,
                "output_preview": _preview_output(getattr(r, "output", "")),
                "error": getattr(r, "error", None),
            }
            for r in exec_records
        ],
        "tool_observations": tool_messages,
        "errors_detected": error_summaries,
    }
    return f"Evalúa la siguiente evidencia contra el objetivo del usuario:\n{json.dumps(user_payload, indent=2, ensure_ascii=False)}"
