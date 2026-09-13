### ✅ Resolución y Cierre de Issue [AGENTE-LOGIC-02]

**Issue:** [jg_agente#67](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/67)
**Título:** [AGENTE-LOGIC-02] Fallback Ciego en plan_node Ejecuta Herramienta Arbitraria con Argumentos Vacíos
**Severidad:** 🟠 ALTO

---

#### 1. Causa Raíz Identificada
En `jg_agente/app/nodes/plan.py`, cuando el motor de planificación fallaba o no producía un plan estructurado, el código recurría a una cláusula de fallback ciego que seleccionaba la primera herramienta registrada en el catálogo (`available_tools[0]`) y le asignaba argumentos vacíos `{}`. Posteriormente, debido a que `GraphBuilder` enlazaba de forma estática `plan` con `execute` o `risk_assess`, dicha herramienta no solicitada se ejecutaba incondicionalmente en el sistema, generando un comportamiento errático y potencialmente destructivo.

#### 2. Cambios Implementados
- **Erradicación del Fallback Ciego en `plan_node`:**
  - En `jg_agente/app/nodes/plan.py`, se eliminó la selección de `available_tools[0]`. Ante ausencia de plan estructurado y de `tool_calls` directas previas, el plan se fija con `steps = []`.
  - Se registra formalmente un `ExecutionError(code="PLANNING_FAILED", fatal=True)` y se marca el estado del agente como `AgentExecutionStatus.FAILED`.
- **Enrutamiento Condicional en LangGraph (`route_after_plan`):**
  - En `jg_agente/app/core/graph.py`, se actualizó el router `route_after_plan` para comprobar si el plan carece de pasos, si el estado es `FAILED`, o si existen errores fatales, derivando en tales casos directamente a `"conclude"`.
  - En `GraphBuilder.build()`, se reemplazó la arista rígida por `builder.add_conditional_edges("plan", ...)` con mapa de destinos explícito (`conclude`, `execute`, `risk_assess`).
- **Priorización de Respuesta de Error en `conclude_node`:**
  - En `jg_agente/app/nodes/conclude.py`, se asegura que si `is_failed` es `True`, la respuesta consolidada priorice el reporte del fallo de planificación sobre respuestas conversacionales previas generadas por el LLM.
- **Actualización de Documentación:**
  - En `jg_agente/docs/graph.md` (Sección 9), se documentó la contención segura ante fallos del nodo de planificación.
- **Cobertura de Pruebas Unitarias e Integradas:**
  - En `jg_agente/tests/test_node_plan.py`, se actualizaron las pruebas unitarias y se incorporó `test_plan_node_failure_routes_to_conclude_without_executing_tools`, comprobando en un grafo real compilado que una falla de planificación desvía a `conclude` sin ejecutar ninguna herramienta del registro.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Formato y tipado estricto 100% conformes sin advertencias (`Success: no issues found in 106 source files`, 106 archivos formateados).
- **Pytest Plan Node:** 9/9 tests pasando en 0.05s.
- **Verificación Global (`./check_unit.sh`):**
  - `jg_agente`: PASÓ (Ruff, MyPy y Pytest correctos).
  - `jg_dashboard`: PASÓ (Pest y pruebas PHP correctas).
