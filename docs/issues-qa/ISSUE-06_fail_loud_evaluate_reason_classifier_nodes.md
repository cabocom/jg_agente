# [ISSUE-06] [jg_agente] fix(nodes): Eliminar falsificación de GoalStatus.SATISFIED y silenciamiento de errores LLM en evaluate, reason_classifier, reason_plan_expander y llm_openai

- **ID Maestro QA:** `ISSUE-06`
- **Proyecto Destino:** `javiergalvez-ia/jg_agente`
- **Asignado a:** `cabocom` / Javier Gálvez (`assignee_ids: [553306]`)
- **Milestone:** `QA & Anti-Fallback Hardening (Nov-Dic 2026)`
- **Labels:** `qa-audit, priority::blocker, anti-fallback`
- **GitLab Issue Remoto:** [jg_agente#87](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/87)

---

- **Severidad y Categoría:** `Blocker` | `Anti-Fallback IA`
- **Consenso de Auditores:** Detectado por: `argon`, `claude-sonnet`, `hydrogen` (`reason_classifier` también por `flash-3.8`)
- **Evidencia Exacta:**
  - `jg_agente/app/nodes/evaluate.py:128-134, 174`
  - `jg_agente/app/nodes/evaluate_parser.py:52-87`
  - `jg_agente/app/nodes/reason_classifier.py:20-35, 45-46, 66-73`
  - `jg_agente/app/nodes/reason_plan_expander.py:216-219`
  - `jg_agente/app/nodes/reason.py:57-61`
  - `jg_agente/app/core/llm_openai.py:83-87`
  ```python
  # jg_agente/app/nodes/evaluate.py:128-134
  except Exception as exc:
      logger.error("[evaluate_node] Fallo invocando al evaluador LLM: %s", exc)
      explanation = f"Evaluación defensiva ante indisponibilidad del modelo evaluador: {exc}"
      goal_status = GoalStatus.FAILED if errors else GoalStatus.SATISFIED
  ```
- **Solución Técnica Propuesta:**
  1. En `evaluate.py:128-134`, cuando el LLM evaluador lanza excepción, fijar siempre `goal_status = GoalStatus.FAILED`, `is_resolved = False` y añadir un `ExecutionError(code="LLM_EVALUATION_FAILED", fatal=True)` al estado.
  2. En `evaluate_parser.py:52-87`, cambiar el estado por defecto ante salida vacía, JSON inválido o `goal_status` irreconocible a `GoalStatus.FAILED` (o `GoalStatus.INCOMPLETE`).
  3. En `reason_classifier.py:20-73`, eliminar `_is_isolated_pure_greeting` (o confinarlo a `MockChatModel`) y propagar las excepciones de inferencia del LLM.
  4. En `reason_plan_expander.py:216-219`, `reason.py:57-61` y `llm_openai.py:83-87`, no absorber errores de expansión de plan HITL, fallos de `bind_tools` ni JSON corrupto en argumentos de `tool_calls`.
- **Criterios de Aceptación (Checklist verificable):**
  - [ ] En `tests/test_node_evaluate.py`, un fallo del LLM evaluador produce `GoalStatus.FAILED` e `is_resolved=False` (nunca `GoalStatus.SATISFIED`).
  - [ ] Un JSON truncado en `evaluate_parser.py` o en `tool_calls` de `llm_openai.py` no se marca como `SATISFIED` ni se envuelve silenciosamente en `{"input": raw_args}`.
  - [ ] `ruff check .` y `pytest` pasan al 100%.
