# Contexto del Proyecto: [AGENTE-LOGIC-04] Contención Secuencial Rígida Aborta Todo el Plan Ante el Primer Fallo

## Metadatos de la Incidencia
- **ID:** `jg_agente#69`
- **Código:** `AGENTE-LOGIC-04`
- **Severidad:** 🟡 MEDIO
- **Ubicación:** [`jg_agente/app/nodes/execute.py:350-380`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/execute.py)
- **Componentes relacionados:**
  - [`jg_agente/app/models/state.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/state.py) (`PlanStep`, `ExecutionPlan`)
  - [`jg_agente/app/models/tools.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/tools.py) (`AgentTool`)
  - [`jg_agente/app/nodes/execute.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/execute.py)
  - [`jg_agente/app/nodes/evaluate.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/evaluate.py)
  - [`jg_agente/app/nodes/plan.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/plan.py)

---

## Descripción del Problema
En `execute_node`, el bucle de ejecución itera secuencialmente sobre `steps_to_run`. Ante cualquier fallo de una herramienta (`if not tool_result.success:`), el código ejecuta incondicionalmente un `break`, abortando de inmediato todos los pasos restantes del plan, sin importar si el paso fallido era crítico o si constituía una comprobación opcional, diagnóstica o de verificación no fatal.

Además, si todos los fallos son catalogados rígidamente o abortan la cadena sin soporte para pasos tolerantes a fallos, el bucle reflexivo (`evaluate -> reason -> plan`) queda privado de la información que los pasos no dependientes posteriores habrían recabado, o puede abortar antes de explorar alternativas de remediación.

---

## Solución Propuesta
1. Extender `PlanStep` (y opcionalmente `AgentTool`) con el atributo `allow_failure: bool = Field(default=False)`.
2. En `execute_node`, evaluar `allow_fail = getattr(step, "allow_failure", False) or getattr(tool, "allow_failure", False)`.
   - Si `allow_fail` es `True`: registrar el fallo en `execution_records` y `errors` con `fatal=False`, pero continuar ejecutando los pasos restantes del plan en lugar de abortar con `break`.
   - Si `allow_fail` es `False`: registrar el error y abortar los pasos posteriores (`break`), derivando hacia la fase de evaluación.
3. En `evaluate_node`, asegurar que errores no fatales no fuercen erróneamente un estado `GoalStatus.FAILED` en modos fallback defensivos.
4. Desarrollar pruebas unitarias completas en `test_node_execute.py` validando la continuación secuencial cuando un paso declara `allow_failure=True`, el aborto cuando declara `allow_failure=False` y la integración con herramientas y evaluación.
