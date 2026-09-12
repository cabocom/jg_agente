### ✅ Implementación Finalizada: [LOOP-ISSUE-AGENT-009] Nodo de evaluación semántica (evaluate_node) y Capability-Awareness

Se ha completado e integrado con éxito el segundo hito del refactor de looping proactivo:

1. **Nodo Cognitivo Evaluador (`app/nodes/evaluate.py`, `app/nodes/__init__.py`):**
   - Implementado `evaluate_node(state, registry, llm=None)` con invocación a `get_chat_model()` (Groq / `openai/gpt-oss-120b`).
   - Evalúa la suficiencia técnica de las herramientas ejecutadas contra la meta del usuario.
   - Emite `EvaluationRecord`, `CognitiveStepRecord` y actualiza `is_resolved`.

2. **Lógica de Capability-Awareness y Honestidad Proactiva:**
   - Detección precisa de herramientas ausentes en el catálogo ante anomalías o fallos observados.
   - Emisión de `GoalStatus.BLOCKED_MISSING_CAPABILITY` con reporte estructurado de `missing_capabilities`.
   - Auto-corrección ante herramientas sugeridas no disponibles en el registro.

3. **Resiliencia y Formateo:**
   - Parsing defensivo de JSON con extracción limpia de bloques markdown.
   - Fallback defensivo ante caídas o tiempos de espera de la API del LLM.

4. **Calidad y Pruebas:**
   - Nueva suite `tests/test_node_evaluate.py` (6/6 passed).
   - Pipeline de calidad (`bash scripts/check.sh`) validado al 100% (Ruff, MyPy y Pytest).

- **GitLab Issue:** [#50](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/50)
- **Estado:** CERRADO / LISTO PARA ISSUE-010
