# Walkthrough: Remediación AGENTE-LOGIC-02 (Eliminación de Fallback Ciego en plan_node)

## 1. Resumen de la Intervención
- **Vulnerabilidad remediada:** [jg_agente#67](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/67) - `[AGENTE-LOGIC-02] Fallback Ciego en plan_node Ejecuta Herramienta Arbitraria con Argumentos Vacíos`.
- **Severidad:** 🟠 ALTO.
- **Alcance:**
  - `jg_agente/app/nodes/plan.py`: Eliminación del bloque de fallback ciego que seleccionaba `available_tools[0]` con `tool_args={}`. Manejo fail-safe registrando `ExecutionError(code="PLANNING_FAILED", fatal=True)` y fijando el estado en `AgentExecutionStatus.FAILED`.
  - `jg_agente/app/core/graph.py`: Actualización del router condicional `route_after_plan` para detectar planes vacíos o estados fallidos y derivar inmediatamente a `conclude`. Conexión de `plan` mediante `add_conditional_edges` en lugar de una arista fija a ejecución.
  - `jg_agente/app/nodes/conclude.py`: Priorización de reporte de error explícito en `conclude_node` ante ejecuciones con estado `is_failed == True`, evitando enmascarar errores de planificación con mensajes conversacionales previos.
  - `jg_agente/docs/graph.md`: Documentación formal de la contención segura ante fallos del nodo de planificación.
  - `jg_agente/tests/test_node_plan.py`: Actualización de pruebas unitarias y adición de prueba de integración en grafo LangGraph compilado verificando que la planificación fallida concluye sin ejecutar herramientas arbitrarias.

---

## 2. Cambios de Código Detallados

### A. Nodo de Planificación (`jg_agente/app/nodes/plan.py`)
1. **Eliminación del Fallback Peligroso:**
   - Se suprimió la rama `elif registry is not None:` que extraía `available_tools[0]`.
2. **Registro de Fallo Formal (`PLANNING_FAILED`):**
   - Si no hay `tool_calls` directas en el intento del agente ni se generó un plan estructurado, se emite un error fatal:
     ```python
     errors.append(
         ExecutionError(
             code="PLANNING_FAILED",
             message="No fue posible generar un plan estructurado válido para la solicitud.",
             component="plan",
             fatal=True,
         )
     )
     ```
   - El estado del agente se actualiza a `AgentExecutionStatus.FAILED`.
   - `CognitiveStepRecord` registra `action="Fallo de Planificación"` y `status="failed"`.

### B. Enrutamiento en Grafo (`jg_agente/app/core/graph.py`)
1. **Router Condicional `route_after_plan`:**
   - Si `plan` no tiene pasos (`not has_steps`), existe un error fatal, o el estado es `FAILED`, enruta hacia `"conclude"`.
   - Si el plan es válido, continúa hacia `"risk_assess"` o `"execute"`.
2. **Aristas Condicionales en `GraphBuilder`:**
   - Sustitución de `builder.add_edge("plan", "execute")` por `builder.add_conditional_edges("plan", lambda s: route_after_plan(...), path_map=...)`.

### C. Nodo de Conclusión (`jg_agente/app/nodes/conclude.py`)
- Se garantiza que si `is_failed` es `True`, la respuesta sintetizada priorice el mensaje de error de planificación frente a `AIMessage` conversacionales previos del LLM.

### D. Pruebas Unitarias e Integradas (`jg_agente/tests/test_node_plan.py`)
- `test_plan_node_without_planner_fails_safe_without_arbitrary_tools`: Verifica que sin plan ni `tool_calls` previas, el nodo no genera pasos (`len(steps) == 0`), fija `FAILED` y registra `PLANNING_FAILED`.
- `test_plan_node_captures_engine_exception`: Verifica que excepciones de un motor planificador marcan `FAILED` sin invocar herramientas.
- `test_plan_node_failure_routes_to_conclude_without_executing_tools`: Prueba de integración sobre grafo LangGraph compilado que demuestra que ante fallo de planificación, el grafo deriva a `conclude` con estado `FAILED` y ninguna herramienta del registro es invocada.

---

## 3. Verificación y Resultados
- **Ruff & MyPy:** 100% de archivos conformes (`All checks passed!`, `Success: no issues found in 106 source files`).
- **Pytest Plan Node:** 9/9 tests pasando en 0.05s.
- **Pytest Suite Completa:** Superada con éxito.
