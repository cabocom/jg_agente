# Análisis Técnico: [LOOP-ISSUE-AGENT-008] Extensión de AgentState, contratos de iteración y preparación de mensajes

## 1. Diagnóstico del Estado Previo

### 1.1 Limitaciones en `app/models/state.py`
En el modelo actual:
- No existen campos para controlar en qué ciclo de razonamiento se encuentra la ejecución (`iteration`, `max_iterations`).
- No existe un modelo para almacenar los resultados de la evaluación semántica post-ejecución (`EvaluationRecord`).
- Si un grafo intentara regresar al nodo `reason`, no dispondría de un registro tipado de por qué se reintentó o qué meta sigue pendiente.

### 1.2 Restricción en `app/core/checkpointer.py`
`JsonPlusSerializer` de LangGraph utiliza una lista blanca estricta (`STATE_ALLOWED_CLASSES`) para deserializar instancias de Pydantic/dataclasses. Si se introducen nuevos modelos en el estado sin registrarlos previamente, cualquier intento de guardar o restaurar un checkpoint en PostgreSQL (`DualPostgresSaver`) lanzará una excepción de deserialización no autorizada.

### 1.3 Pérdida de Contexto en `app/nodes/execute.py`
En `app/nodes/execute.py:289-303`:
```python
# Si procede de un tool_call del LLM, emitir ToolMessage para la memoria
if is_tool_call_source:
    tool_messages.append(
        ToolMessage(
            content=msg_content,
            tool_call_id=step.step_id,
            name=step.tool_name,
        )
    )
```
Si los pasos provienen de un plan estructurado (`ExecutionPlan`), `is_tool_call_source` es `False`. Como consecuencia, `tool_messages` no incluye la salida de esas herramientas en `messages`. Al volver a invocar a `reason`, el LLM solo tiene en su historial el prompt original del usuario, ignorando completamente los resultados técnicos que las herramientas ya obtuvieron.

---

## 2. Solución Diseñada

### 2.1 Modelos de Datos en `app/models/state.py`
1. `GoalStatus(StrEnum)`:
   - `SATISFIED`: La evidencia responde completamente a la petición del usuario.
   - `NEEDS_MORE_INFO`: Se requiere una acción o herramienta adicional para completar el objetivo.
   - `BLOCKED_MISSING_CAPABILITY`: Se identificó una necesidad técnica ausente en el catálogo de herramientas del agente (ej. falta `docker:logs`).
   - `FAILED`: Fallo irrecuperable o crítico.

2. `EvaluationRecord(BaseModel)`:
   - Contiene `iteration`, `goal_status`, `explanation`, `missing_capabilities`, `suggested_next_action` y `timestamp`.

3. Extensión de `AgentState(TypedDict)`:
   - `iteration: int` (default 1)
   - `max_iterations: int` (default 3)
   - `evaluation_records: Annotated[list[EvaluationRecord], append_reducer]`

### 2.2 Registro en `app/core/checkpointer.py`
Incorporación a `STATE_ALLOWED_CLASSES`:
```python
(("app.models", "GoalStatus"),)
(("app.models.state", "GoalStatus"),)
(("app.models", "EvaluationRecord"),)
(("app.models.state", "EvaluationRecord"),)
```

### 2.3 Emisión Universal de `ToolMessage` en `app/nodes/execute.py`
Eliminar la restricción `if is_tool_call_source:`. Para cualquier paso ejecutado exitosamente o con fallo, se genera un `ToolMessage` con:
- `tool_call_id = step.step_id`
- `name = step.tool_name`
- `content = str(tool_result.output) if tool_result.success else f"Error ejecutando {tool.name}: {tool_result.error}"`

De esta forma, `state["messages"]` preserva la historia fidedigna de todas las observaciones técnicas para cualquier re-evaluación del LLM.

---

## 3. Plan de Verificación
1. **Tests unitarios específicos:** `tests/test_loop_state_contracts.py` comprobando:
   - Inicialización y valores por defecto en `AgentState`.
   - Serialización y deserialización a través de `checkpointer.py` con `EvaluationRecord` y `GoalStatus`.
   - Generación de `ToolMessage` en `execute_node` tanto para llamadas directas como para pasos de plan.
2. **Suite global de tests:** Ejecutar `pytest` sobre todos los tests existentes para garantizar 0 regresiones.
