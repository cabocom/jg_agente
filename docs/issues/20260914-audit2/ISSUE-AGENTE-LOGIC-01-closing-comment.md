### ✅ Resolución y Cierre de Issue [AGENTE-LOGIC-01]

**Issue:** [jg_agente#66](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/66)
**Título:** [AGENTE-LOGIC-01] Heurística Sintáctica en Español Clasifica Comandos como Saludos
**Severidad:** 🟠 ALTO

---

#### 1. Causa Raíz Identificada
El método `_is_simple_greeting_or_chat` en `jg_agente/app/nodes/reason.py` empleaba tuplas estáticas con prefijos interrogativos en español (`question_starters`: "dime", "cuál", "explica", "cuenta", etc.) y palabras clave operativas fijadas (`operational_keywords`: "reinicia", "mata", "despliega", etc.). Esto provocaba que cualquier consulta de infraestructura o diagnóstico formulada en lenguaje natural cotidiano (ej. *"Dime el estado de los contenedores"*, *"¿Cuál es el uso de memoria de los pods?"*) fuese catalogada erróneamente como un saludo/charla casual, silenciando al planificador y abortando el acceso a herramientas operativas. Además, mantener diccionarios de verbos de dominio en el Core violaba el principio arquitectónico de "Agnosticismo Radical del Core".

#### 2. Cambios Implementados
- **Eliminación de Heurísticas Sintácticas en el Core:**
  - Se suprimieron las listas hardcodeadas de verbos operativos y prefijos interrogativos en `jg_agente/app/nodes/reason.py`.
- **Clasificación Semántica de Intenciones con IA (`_is_simple_greeting_or_chat_llm`):**
  - Se implementó la corrutina asíncrona de clasificación mediante llamada al LLM con un rol de sistema binario estricto (`GREETING` vs. `ACTION`).
  - Se incorporó un atajo léxico directo de latencia cero reservado exclusivamente a fórmulas de cortesía elementales aisladas (1-2 palabras como "hola", "buenos días").
  - Comportamiento **Fail-Open Operativo**: Ante excepciones de red o timeout del LLM, el clasificador asume `False` (intención `ACTION`), garantizando que ninguna orden de un operador sea desestimada.
- **Actualización de la Documentación del Agente:**
  - `jg_agente/docs/graph.md`: Documentación completa de la nueva llamada a la IA en la Sección 5 (especificación de prompt, parámetros, comportamiento fail-open y atajo de cortesía).
  - `jg_agente/docs/architecture.md`: Actualización del Principio de Agnosticismo Radical del Core en la Sección 1, formalizando la prohibición de diccionarios léxicos de dominio en el Core.
- **Soporte en Emulador de Pruebas (`MockChatModel`):**
  - En `jg_agente/app/core/llm.py`, se dotó a `MockChatModel` de discriminación semántica para el rol de clasificador de intenciones, permitiendo probar saludos y consultas de capacidades frente a consultas operativas de infraestructura.
- **Cobertura de Pruebas Unitarias:**
  - En `jg_agente/tests/test_node_reason.py`, se añadió la suite `TestReasonNodeIntentClassification` validando saludos simples frente a consultas operativas con prefijos en español ("Dime el estado de los contenedores", "¿Cuál es el uso de memoria de los pods?", etc.), verificando su derivación automática al planificador (`plan`).

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Tipado estricto y formato 100% limpios sin advertencias (`Success: no issues found in 106 source files`, 106 archivos formateados).
- **Pytest Agente:** Pruebas unitarias de `test_node_reason.py` pasando con éxito (10/10 en 0.05s).
- **Suite Completa y Verificación Global:** Verificación integral mediante `./check_unit.sh`.
