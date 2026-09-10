# Análisis Técnico: [ISSUE-AGENT-004] Aplicación y prueba de timeout_sec y cancelación en herramientas

## 1. Diagnóstico del Estado Previo
En el estado previo de `jg_agente`:
- `AgentTool` declaraba el atributo `timeout_sec: float = Field(default=30.0, gt=0.0)`.
- Sin embargo:
  - `AgentTool.run()` ejecutaba directamente `self.func(*args, **kwargs)` en el mismo hilo sin control de timeout.
  - `SecurityGuard.execute_tool()` ejecutaba directamente `tool.func(**sanitized_args)` como una llamada síncrona sin timeout.
  - `execute_node()` en `app/nodes/execute.py` ejecutaba `guard.execute_tool()` sin ningún límite de tiempo. Si la salida era una corrutina, realizaba `await tool_result.output` sin `asyncio.wait_for`.
- Si una herramienta de integración entraba en un bloqueo indefinido o un socket no respondía, el worker de Uvicorn/FastAPI quedaba permanentemente inutilizado.

## 2. Solución Diseñada

### 2.1 `SecurityGuard.execute_tool`
- Se rediseñó el método como una corrutina `async def execute_tool(...) -> ToolResult:`.
- Detección de naturaleza de la herramienta:
  - Si es asíncrona (`inspect.iscoroutinefunction`): se invoca y se espera mediante `await asyncio.wait_for(_invoke_async(), timeout=timeout_sec)`.
  - Si es síncrona: se delega a un hilo de trabajo con `asyncio.to_thread(_invoke_sync)` y se envuelve en `await asyncio.wait_for(..., timeout=timeout_sec)`. Esto previene el bloqueo del hilo principal del bucle de eventos.
- Captura explícita de `TimeoutError`:
  - Retorna `ToolResult(success=False, error="TimeoutError: ...", metadata={"timeout_sec": timeout_sec, "timed_out": True})`.
  - Registra el evento de auditoría en `SecurityAuditLogger.record_tool_execution`.

### 2.2 `execute_node`
- Invocación de `guard.execute_tool` bajo `asyncio.wait_for` defensivo con `timeout=timeout_sec`.
- Captura de `TimeoutError` asignando:
  - `step.status = StepStatus.FAILED`
  - `StepExecutionRecord` con `status=StepStatus.FAILED` y mensaje de error descriptivo.
  - `ExecutionError` con código `code="TOOL_TIMEOUT"`.
- Activación de contención secuencial (`break` del bucle de pasos del plan) para evitar la ejecución en cascada de pasos dependientes.
- Retorno limpio de mutaciones de estado para LangGraph.

### 2.3 `AgentTool.run`
- Incorporación de timeout síncrono mediante `concurrent.futures.ThreadPoolExecutor(max_workers=1)`.
- `future.result(timeout=timeout)` captura `TimeoutError` y devuelve `ToolResult` fallido de forma normalizada.

## 3. Impacto en Pruebas
- Actualización de `TestSecurityGuardExecution` en `tests/test_security_guard.py` a métodos asíncronos (`async def`).
- Inclusión de pruebas unitarias para timeouts en herramientas asíncronas y síncronas en `SecurityGuard`.
- Inclusión de pruebas unitarias en `tests/test_node_execute.py` validando la contención, el código `TOOL_TIMEOUT` y la marcación de `StepStatus.FAILED`.
- Inclusión de prueba unitaria en `tests/test_tool_models.py` para `AgentTool.run()`.
