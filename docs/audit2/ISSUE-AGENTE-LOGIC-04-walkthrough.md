# Walkthrough - [AGENTE-LOGIC-04] Contención Secuencial Rígida Aborta Todo el Plan Ante el Primer Fallo

## Resumen Ejecutivo

- **Issue:** [jg_agente#69](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/69) - `[AGENTE-LOGIC-04] Contención Secuencial Rígida Aborta Todo el Plan Ante el Primer Fallo`
- **Severidad:** 🟡 MEDIO
- **Componentes Afectados:**
  - [`app/models/state.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/state.py) (`PlanStep`)
  - [`app/models/tools.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/tools.py) (`AgentTool`)
  - [`app/nodes/execute.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/execute.py)
  - [`app/nodes/plan.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/plan.py)
  - [`tests/test_node_execute.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/tests/test_node_execute.py)

---

## Causa Raíz

En el bucle de ejecución de herramientas de `execute_node`, cualquier fallo técnico u operacional provocaba la terminación inmediata del bucle mediante un `break` incondicional (`if not tool_result.success: break`). Esto ocasionaba que:
1. Pasos de diagnóstico, comprobación previa o verificación no fatal que experimentaran fallos temporales abortaran la ejecución de pasos primarios no dependientes subsiguientes.
2. El bucle reflexivo (`evaluate -> reason -> plan`) quedara privado de la información que los pasos posteriores habrían recabado, o se viera forzado a abortar prematuramente.

---

## Solución Implementada

1. **Soporte de Esquema para Tolerancia a Fallos:**
   - En [`app/models/state.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/state.py), se añadió el campo `allow_failure: bool = Field(default=False)` al modelo `PlanStep`.
   - En [`app/models/tools.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/tools.py), se añadió el campo `allow_failure: bool = Field(default=False)` al modelo de descriptor de capacidad `AgentTool`.

2. **Contención Secuencial Flexible en `execute_node`:**
   - En [`app/nodes/execute.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/execute.py):
     - Se evalúa si el paso o la herramienta admiten fallos no fatales: `allow_fail = bool(getattr(step, "allow_failure", False) or (tool and getattr(tool, "allow_failure", False)))`.
     - Si `allow_fail` es `True`: se registra el fallo en `execution_records` con `StepStatus.FAILED`, se añade un `ExecutionError(fatal=False)`, se genera el salto cognitivo y se emite el `ToolMessage` correspondiente, pero **no se aborta la cadena con `break`**, permitiendo que los pasos restantes continúen ejecutándose.
     - Si `allow_fail` es `False`: se mantiene la contención secuencial estricta abortando con `break` y registrando el fallo para evaluación reflexiva.
     - Mismo comportamiento ante herramientas no registradas (`TOOL_NOT_FOUND`).

3. **Propagación en `plan_node`:**
   - En [`app/nodes/plan.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/plan.py), la formulación de pasos fallback propaga automáticamente el atributo `allow_failure` definido a nivel de herramienta o en los argumentos de la llamada.

4. **Batería de Pruebas Automatizadas:**
   - Se incorporaron 4 tests unitarios específicos en [`tests/test_node_execute.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/tests/test_node_execute.py):
     - `test_execute_node_continues_when_step_allows_failure`: valida que un paso con `allow_failure=True` que falla no aborta los pasos 2 y 3.
     - `test_execute_node_aborts_when_step_disallows_failure`: valida que `allow_failure=False` detiene la cadena inmediatamente en el paso fallido.
     - `test_execute_node_tool_level_allow_failure`: valida que la configuración a nivel de `AgentTool.allow_failure` se respeta automáticamente en el paso.
     - `test_execute_node_tool_not_found_with_allow_failure`: valida que una herramienta no encontrada tolerante no detiene los pasos subsiguientes.
