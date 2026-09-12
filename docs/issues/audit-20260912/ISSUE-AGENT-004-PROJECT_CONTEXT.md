# Contexto de Proyecto: [ISSUE-AGENT-004] Aplicación y prueba de timeout_sec y cancelación en herramientas

## 1. Identificación y Estado
- **Issue ID:** ISSUE-AGENT-004
- **GitLab Item:** #45 (jg_agente)
- **Vínculo Auditoría:** AGENT-004
- **Fase:** Fase Post-Auditoría (Implementación de Hallazgos Codex)
- **Prioridad:** Medium / Operations
- **Complejidad Estimada:** M
- **Estado:** Implementado / Verificado

## 2. Alineación Arquitectónica
En la auditoría técnica independiente (hallazgo AGENT-004), se constató que el atributo `timeout_sec` declarado en el contrato canónico `AgentTool` (con valor por defecto de 30.0 segundos) era meramente declarativo y no se aplicaba ni en `AgentTool.run()` ni en `SecurityGuard.execute_tool()` ni en el nodo de grafo `execute_node()`.

Esto provocaba un riesgo operacional severo: si una herramienta de red, Docker SDK, consulta de base de datos o cómputo intensivo entraba en un bloqueo indefinido o superaba los tiempos admisibles, el worker del agente (FastAPI / Uvicorn) quedaba retenido de forma permanente, bloqueando la capacidad de respuesta para todas las demás ejecuciones y solicitudes de gobierno HITL.

Para solucionar este defecto de forma no bloqueante y respetando el modelo de concurrencia de Python:
1. **`SecurityGuard.execute_tool` Asíncrono y No Bloqueante:**
   - Se convirtió `execute_tool()` en método asíncrono (`async def execute_tool`).
   - Para herramientas asíncronas (`inspect.iscoroutinefunction`), se envuelve su ejecución bajo `asyncio.wait_for(coro, timeout=timeout_sec)`.
   - Para herramientas síncronas bloqueantes, se despachan al pool de hilos mediante `asyncio.to_thread(_invoke)` bajo `asyncio.wait_for(..., timeout=timeout_sec)`. De este modo, las operaciones síncronas no congelan el event loop de FastAPI.
   - Ante `TimeoutError`, se captura la excepción, se calcula el tiempo transcurrido, se registra en `SecurityAuditLogger` y se retorna un `ToolResult(success=False, error=..., metadata={"timeout_sec": timeout_sec, "timed_out": True})`.
2. **`execute_node` con Contención y Tolerancia a Fallos:**
   - Envuelve `guard.execute_tool()` en `asyncio.wait_for` defensivo con el límite `tool.timeout_sec`.
   - Captura `TimeoutError` asignando `step.status = StepStatus.FAILED` y `StepExecutionRecord` con `status=StepStatus.FAILED`.
   - Agrega un `ExecutionError` tipado con `code="TOOL_TIMEOUT"`.
   - Aplica contención secuencial: aborta la ejecución de pasos subsiguientes del plan para evitar encadenar fallos.
   - Consolida y retorna el estado de mutación sin elevar excepciones no controladas ni tumbar el runtime de LangGraph.
3. **`AgentTool.run` Síncrono:**
   - Aplica el límite `timeout_sec` mediante `concurrent.futures.ThreadPoolExecutor(max_workers=1)` y `future.result(timeout=timeout)`.

## 3. Criterios de Aceptación
- `SecurityGuard.execute_tool` aplica `asyncio.wait_for` con `tool.timeout_sec`.
- Herramientas síncronas se ejecutan sin bloquear el event loop (`asyncio.to_thread`).
- `execute_node` captura `TimeoutError`, marca `StepStatus.FAILED` y registra `code="TOOL_TIMEOUT"`.
- Los pasos subsiguientes de un plan se detienen tras un fallo por timeout.
- Se preserva la auditoría inmutable de la herramienta en `core_audit_records`.
- La suite completa de pruebas en `jg_agente` supera los análisis estáticos y pruebas unitarias (330 tests pasados al 100%).
