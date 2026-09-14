# Análisis Técnico: ISSUE-AGENTE-LOGIC-01

**Issue:** [jg_agente#66](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/66)  
**Título:** [AGENTE-LOGIC-01] Heurística Sintáctica en Español Clasifica Comandos como Saludos  
**Severidad:** 🟠 ALTO  
**Ubicación:** `jg_agente/app/nodes/reason.py:37-170, 298`  

---

## 1. Causa Raíz
En `jg_agente/app/nodes/reason.py`, la función `_is_simple_greeting_or_chat` implementaba una heurística basada en listas estáticas de palabras y prefijos interrogativos:
1. `operational_keywords`: Lista cerrada de verbos imperativos de mutación (`reinicia`, `apaga`, `mata`, `despliega`, etc.).
2. `question_starters`: Prefijos de preguntas en español (`dime`, `cuenta`, `explica`, `qué`, `cómo`, `cuál`, `cuáles`, `por qué`, etc.).

Si el usuario introducía cualquier consulta en lenguaje natural que comenzara con uno de estos prefijos (ej. *"Dime el estado de los contenedores"*, *"¿Cuál es el uso de CPU?"*, *"Explica los errores en los logs"*), la regla asumía que era una conversación simple porque no contenía un verbo imperativo de la lista cerrada.

Como consecuencia:
- `_is_simple_greeting_or_chat(prompt)` devolvía `True`.
- La condición `elif planner_engine is not None and not _is_simple_greeting_or_chat(prompt):` evaluaba a `False`.
- El agente concluía de forma prematura con una respuesta estática o alucinada del LLM, puenteando el planificador y la invocación de herramientas de lectura.
- Además, la presencia de palabras clave de dominios concretos en el Core violaba el principio de **Agnosticismo Radical del Core**.

---

## 2. Solución Arquitectónica
1. **Erradicación de Heurísticas Sintácticas y Palabras de Dominio en el Core:**
   Eliminar las listas fijas de verbos y prefijos en `reason.py`.
2. **Determinación Dinámica mediante IA (`_is_simple_greeting_or_chat_llm`):**
   Delegar en el LLM la clasificación semántica cuando no se emiten llamadas directas a herramientas y existe un motor de planificación registrado (`planner_engine is not None`).
3. **Soporte en `MockChatModel`:**
   Dotar al proveedor simulado de testing de soporte para responder `GREETING` o `ACTION` de forma determinista ante el clasificador de intenciones.
4. **Actualización de Documentación:**
   Documentar en `docs/graph.md` la invocación semántica del LLM para clasificación de intenciones.
