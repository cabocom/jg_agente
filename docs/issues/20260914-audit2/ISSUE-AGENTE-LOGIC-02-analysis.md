# Análisis Técnico: ISSUE-AGENTE-LOGIC-02

**Issue:** [jg_agente#67](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/67)  
**Título:** [AGENTE-LOGIC-02] Fallback Ciego en plan_node Ejecuta Herramienta Arbitraria con Argumentos Vacíos  
**Severidad:** 🟠 ALTO  
**Ubicación:** `jg_agente/app/nodes/plan.py:163-178`  

---

## 1. Causa Raíz
En `jg_agente/app/nodes/plan.py`, si `plan is None` (bien porque no hay motor registrado, el motor falló o el LLM no generó un plan estructurado) y el estado no contiene llamadas directas a herramientas en `intent.parameters.get("tool_calls")`:

```python
elif registry is not None:
    available_tools = registry.list_tools()
    if available_tools:
        target_tool = available_tools[0]
        steps.append(
            PlanStep(
                step_id="step-1",
                tool_name=target_tool.name,
                tool_args={},
                description=f"Ejecutar {target_tool.name}",
                risk_level=target_tool.risk_level,
                reversible=target_tool.reversible,
                dependencies=[],
            )
        )
```

El código seleccionaba arbitrariamente la primera herramienta registrada en `registry.list_tools()` y le asignaba argumentos vacíos `{}`.
Posteriormente, el grafo ejecutaba incondicionalmente dicho plan en `execute_node` porque la transición desde `plan` en `GraphBuilder` estaba cableada de forma estática con `builder.add_edge("plan", "execute")` o `builder.add_edge("plan", "risk_assess")`, ignorando si el plan era válido o si se habían producido fallos.

---

## 2. Solución Arquitectónica
1. **Eliminar el Fallback Ciego en `plan_node`:**
   - Suprimir el bloque `elif registry is not None: ... available_tools[0]`.
   - Si no hay `tool_calls` previas y no se generó un plan estructurado, mantener `steps = []`.
   - Registrar `ExecutionError(code="PLANNING_FAILED", message="...", fatal=True)`.
   - Marcar el estado como `AgentExecutionStatus.FAILED`.
2. **Enrutamiento Condicional en LangGraph (`route_after_plan`):**
   - Actualizar `route_after_plan` en `jg_agente/app/core/graph.py` para comprobar si el plan carece de pasos (`not plan.steps`), si el estado es `FAILED`, o si existen errores fatales.
   - En cualquiera de esos casos, retornar `"conclude"`.
   - En `GraphBuilder.build()`, sustituir `builder.add_edge("plan", ...)` por `builder.add_conditional_edges("plan", ...)`.
3. **Validación en Pruebas Unitarias:**
   - Actualizar `test_plan_node_without_planner_fallback` para verificar que la ausencia de un plan válido resulta en `FAILED` sin invocar herramientas arbitrarias.
   - Añadir pruebas de integración en el grafo donde la planificación fallida concluye directamente en `conclude` con estado fallido y sin ejecutar herramientas.
