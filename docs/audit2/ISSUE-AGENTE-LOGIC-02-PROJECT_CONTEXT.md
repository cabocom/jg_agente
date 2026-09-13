# Contexto del Proyecto: AGENTE-LOGIC-02

## 1. Módulo Afectado
- **Ruta principal:** `jg_agente/app/nodes/plan.py`
- **Componentes relacionados:** `jg_agente/app/core/graph.py`, `jg_agente/app/nodes/conclude.py`
- **Severidad:** 🟠 ALTO

---

## 2. Principio Arquitectónico y de Seguridad: No Invocación de Herramientas Ciega
En un agente autónomo que opera sobre sistemas e infraestructuras reales, ninguna herramienta puede ejecutarse sin una orden o plan explícito formulado por un componente cognitivo (LLM, motor de planificación o `tool_calls` verificadas).
Seleccionar la primera herramienta de un catálogo (`available_tools[0]`) y programarla con parámetros vacíos `{}` como mecanismo de fallback cuando la planificación falla introduce un comportamiento errático, no determinista y potencialmente destructivo (por ejemplo, si la primera herramienta del catálogo es de mutación o reinicio de servicios).

---

## 3. Comportamiento Esperado tras la Remediación
- Si el planificador o el modelo falla en generar un plan estructurado y no existen `tool_calls` explícitas del razonamiento:
  1. `plan_node` no selecciona ninguna herramienta por defecto (`steps = []`).
  2. Registra un `ExecutionError(code="PLANNING_FAILED", fatal=True)` y marca el estado en `FAILED`.
  3. El enrutador condicional de LangGraph `route_after_plan` deriva directamente hacia `conclude`.
  4. `conclude_node` sintetiza la salida de error informando que la planificación no pudo completarse, impidiendo la ejecución de herramientas arbitrarias.
