# Walkthrough: Remediación AGENTE-LOGIC-01 (Clasificación Semántica de Intenciones con IA en el Nodo Reason)

## 1. Resumen de la Intervención
- **Defecto remediado:** [jg_agente#66](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/66) - `[AGENTE-LOGIC-01] Heurística Sintáctica en Español Clasifica Comandos como Saludos`.
- **Severidad:** 🟠 ALTO.
- **Alcance:**
  - `jg_agente/app/nodes/reason.py`: Eliminación de listas sintácticas de palabras operativas (`operational_keywords`) y prefijos interrogativos en español (`question_starters`). Implementación de `_is_simple_greeting_or_chat_llm` que delega en el LLM la clasificación binaria semántica entre `GREETING` y `ACTION`.
  - `jg_agente/app/core/llm.py`: Soporte en `MockChatModel` para emular el clasificador de intenciones (`clasificador de intenciones`) distinguiendo saludos y consultas sobre el agente frente a comandos y peticiones operativas.
  - `jg_agente/docs/graph.md`: Actualización de la documentación arquitectónica del nodo `reason` y del ciclo de vida de inferencia, detallando formalmente el contrato de la nueva llamada a la IA, su comportamiento fail-safe/fail-open y sus optimizaciones de latencia.
  - `jg_agente/docs/architecture.md`: Actualización de la sección de principios arquitectónicos ("Agnosticismo Radical del Core") para prohibir explícitamente heurísticas léxicas y asentar la delegación en la IA.
  - `jg_agente/tests/test_node_reason.py`: Inclusión de la suite `TestReasonNodeIntentClassification` para verificar la distinción entre saludos conversacionales y comandos operativos en lenguaje natural (ej. *"Dime el estado de los contenedores"*, *"¿Cuál es el uso de memoria de los pods?"*).

---

## 2. Cambios de Código Detallados

### A. Nodo Cognitivo Troncal (`jg_agente/app/nodes/reason.py`)
1. **Eliminación de Heurísticas Sintácticas Rígidas:**
   - Se eliminaron las listas `question_starters` ("dime", "cuál", "explica", "cuenta") y `operational_keywords` ("reinicia", "para", "mata", etc.) que violaban el desacoplamiento entre el Core y los plugins.
2. **Invocación a la IA (`_is_simple_greeting_or_chat_llm`):**
   - Se implementó la corrutina asíncrona:
     ```python
     async def _is_simple_greeting_or_chat_llm(model: BaseChatModel, prompt: str) -> bool:
     ```
   - Inyecta un `SystemMessage` con rol de clasificador de intenciones estricto (`GREETING` vs. `ACTION`).
   - Atajo léxico determinista de baja latencia reservado únicamente a fórmulas aisladas elementales de 1-2 palabras (ej. "hola", "buenos días", "gracias").
   - Comportamiento **Fail-Open Operativo**: Ante cualquier fallo o timeout en la llamada al LLM, la función retorna `False` (intención `ACTION`), garantizando que ninguna orden operativa real sea descartada o silenciada.
3. **Enrutamiento Dinámico en `reason_node`:**
   - Si no hay llamadas a herramientas inmediatas (`tool_calls`) y existe un motor de planificación (`planner_engine`), se consulta al LLM:
     ```python
     elif planner_engine is not None and not await _is_simple_greeting_or_chat_llm(model, prompt):
         intent = IntentModel(..., action_type="plan", ...)
     ```
   - Corrige el valor `step_description` en la rama `has_tool_calls` para garantizar consistencia en la auditoría del paso cognitivo (`CognitiveStepRecord`).

### B. Emulación en Mock (`jg_agente/app/core/llm.py`)
- `MockChatModel._determine_output` detecta mensajes con `"clasificador de intenciones"`.
- Distingue adecuadamente preguntas sobre la identidad y capacidades del agente frente a marcadores operacionales de infraestructura (`estado`, `contenedor`, `docker`, `pod`, `servicio`, `reinicia`, `ejecuta`, `logs`, etc.).

### C. Documentación Técnica
- `jg_agente/docs/graph.md`: Detalla en la Sección 5 la especificación de la llamada a la IA de clasificación semántica, entradas, salidas, fail-open y atajo léxico.
- `jg_agente/docs/architecture.md`: Refuerza el Agnosticismo Radical del Core en la Sección 1 prohibiendo listas de palabras clave operativas en el Core.

### D. Pruebas Unitarias (`jg_agente/tests/test_node_reason.py`)
- `TestReasonNodeIntentClassification.test_llm_distinguishes_greeting_from_operational_query`:
  - Valida que saludos puros ("Hola, buenos días") concluyen directamente (`conclude`).
  - Valida que peticiones en lenguaje natural con prefijos habituales ("Dime el estado de los contenedores", "¿Cuál es el uso de memoria de los pods?", "Explica los errores en los logs del servicio auth", "Cuenta cuántos servicios están caídos") son clasificadas como `ACTION` y derivadas al planificador (`plan`).

---

## 3. Verificación y Resultados
1. **Linter & Formato (`Ruff`):**
   - 100% de archivos formateados y limpios sin advertencias (`All checks passed!`, 106 archivos).
2. **Tipado Estático (`MyPy`):**
   - Modo estricto superado sin errores (`Success: no issues found in 106 source files`).
3. **Pruebas Unitarias Agente (`Pytest`):**
   - `tests/test_node_reason.py`: 10 passed in 0.05s.
