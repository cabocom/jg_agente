### ✅ Implementación Finalizada: [LOOP-ISSUE-AGENT-008] Extensión de AgentState, contratos de iteración y preparación de mensajes

Se han implementado con éxito todos los requisitos del primer hito del refactor de razonamiento iterativo:

1. **Contratos y Modelos de Estado (`app/models/state.py`, `app/models/__init__.py`):**
   - Incorporado enum `GoalStatus` con estados: `SATISFIED`, `NEEDS_MORE_INFO`, `BLOCKED_MISSING_CAPABILITY` y `FAILED`.
   - Incorporado modelo `EvaluationRecord` con seguimiento de iteración, explicación semántica y detección de capacidades ausentes.
   - `AgentState` extendido con `iteration: int`, `max_iterations: int` y `evaluation_records` con reducer `append_reducer`.

2. **Serialización Segura de Checkpoints (`app/core/checkpointer.py`):**
   - Registradas las tuplas de `GoalStatus` y `EvaluationRecord` en `STATE_ALLOWED_CLASSES` para `JsonPlusSerializer` y PostgreSQL.

3. **Memoria de Ejecución Universal (`app/nodes/execute.py`):**
   - Inyección garantizada de `ToolMessage` a `state["messages"]` para todos los pasos de herramientas ejecutados (tanto directos como planificados).

4. **Documentación Global:**
   - Actualizada la especificación viva en `docs/models.md`.

5. **Pruebas Automatizadas:**
   - Nueva suite `tests/test_loop_state_contracts.py` (5/5 passed).
   - Suite completa de integración ejecutada satisfactoriamente con 0 regresiones.

- **GitLab Issue:** [#49](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/49)
- **Estado:** CERRADO / LISTO PARA ISSUE-009
