# Análisis Técnico: [AGENTE-LOGIC-04] Contención Secuencial Rígida Aborta Todo el Plan Ante el Primer Fallo

## Diagnóstico y Estado Actual

En [`jg_agente/app/nodes/execute.py`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/nodes/execute.py#L350-L368):
```python
        # Manejo de fallos operacionales
        if not tool_result.success:
            err_desc = tool_result.error or f"Fallo en la ejecución de '{step.tool_name}'."
            logger.warning("[execute_node] Paso '%s' falló: %s", step.step_id, err_desc)
            is_timeout = bool(tool_result.metadata.get("timed_out"))
            errors.append(
                ExecutionError(
                    code="TOOL_TIMEOUT" if is_timeout else "TOOL_EXECUTION_FAILED",
                    message=err_desc,
                    component="execute",
                    fatal=False,
                )
            )
            # Contención secuencial: abortar pasos posteriores tras el primer fallo
            break
```

### Problemas Detectados
1. **Falta de soporte para pasos opcionales o tolerantes a fallos en el esquema:**
   [`PlanStep`](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/state.py#L117-L135) no contiene ningún campo para indicar si el paso admite fallos no fatales (`allow_failure: bool`).
2. **Abrupción prematura del plan:**
   Si un plan consta de pasos como:
   - Paso 1: `diagnose_cache` (herramienta de comprobación no crítica)
   - Paso 2: `fetch_primary_service_data` (operación principal)
   - Paso 3: `report_status` (notificación)
   Si el Paso 1 falla por timeout o indisponibilidad temporal del caché, el `break` incondicional cancela los Pasos 2 y 3, impidiendo que el agente obtenga los datos primarios.
3. **Coherencia con `evaluate_node` y el bucle reflexivo:**
   Al ejecutarse `execute_node`, el enrutamiento posterior (`route_after_execute`) envía el estado a `evaluate_node`. Si los errores no son fatales y los pasos restantes se ejecutaron, el evaluador puede determinar que el objetivo está satisfecho o pedir más información (`needs_more_info`), permitiendo al agente recuperarse reflexivamente.

---

## Estrategia de Mitigación

1. **Extensión de Esquemas:**
   - En `PlanStep`: añadir `allow_failure: bool = Field(default=False, description="Indica si un fallo en este paso es no fatal y permite continuar con la ejecución del resto del plan")`.
   - En `AgentTool`: añadir `allow_failure: bool = Field(default=False, description="Indica si los fallos de la herramienta son tolerables por defecto")`.

2. **Lógica de Ejecución en `execute_node`:**
   - Evaluar si el paso o la herramienta admiten fallos:
     `allow_fail = bool(getattr(step, "allow_failure", False) or (tool and getattr(tool, "allow_failure", False)))`
   - Si `allow_fail` es True:
     - El paso se marca con `status=StepStatus.FAILED`.
     - Se registra en `execution_records` y `cognitive_steps`.
     - Se agrega a `errors` con `fatal=False`.
     - Se emite el `ToolMessage` con la información del error para que el LLM evaluador tenga evidencia del resultado.
     - **NO se ejecuta `break`**: se continúa con el siguiente paso en `steps_to_run`.
   - Si `allow_fail` es False:
     - Se marca con `status=StepStatus.FAILED`.
     - Se agrega a `errors` con `fatal=False` (para permitir recuperación reflexiva en evaluación, salvo que sea error fatal de sistema).
     - Se ejecuta `break` para detener los pasos subsiguientes del plan actual.

3. **Fallback en `evaluate_node`:**
   - En caso de fallo del LLM evaluador o modo defensivo, verificar `has_fatal_errors = any(getattr(e, "fatal", False) for e in errors)` en vez de asumir `errors` como fallo fatal incondicional.

4. **Compatibilidad:**
   - Al tener `default=False`, todos los planes existentes mantienen el comportamiento seguro de contención secuencial ante fallos críticos.
