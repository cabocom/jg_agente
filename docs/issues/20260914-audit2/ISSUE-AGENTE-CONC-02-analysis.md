# Análisis de Causa Raíz: [AGENTE-CONC-02] Pérdida de Trazabilidad y Notificaciones en Tareas Asíncronas en Background

## Diagnóstico Técnico
1. **Desconexión Asíncrona en el Ciclo de BackgroundTasks:**
   En `app/api/executions.py`:
   ```python
   async def run_in_background(graph: Any, input_data: AgentInput) -> None:
       try:
           await execute_graph_pipeline(graph, input_data)
       except Exception as exc:
           logger.error(...)
   ```
   La función ignoraba el valor retornado por `execute_graph_pipeline(graph, input_data)` y descartaba la excepción tras registrarla en el log. No existía ninguna invocación de red de salida hacia el emisor original ni hacia el Dashboard.

2. **Inexistencia de un Endpoint Receptor Interno en el Control Plane:**
   `jg_dashboard` exponía endpoints para registrar agentes (`POST /api/v1/agents/register`) y recibir latidos periódicos (`POST /api/v1/agents/heartbeat`), pero carecía de una ruta interna autorizada para la recepción de eventos de ciclo de vida de ejecuciones enviadas por los agentes (`POST /api/v1/internal/executions/{id}/complete`).

3. **Inflexibilidad ante Invocadores Externos:**
   El contrato `AgentInput` no exponía formalmente un campo `callback_url` tipado, impidiendo que clientes externos (sistemas de terceros, colas de mensajería, chatbots) especificasen una URL destino propia para recibir webhooks de conclusión.

## Estrategia de Solución
1. **Emisión de Webhooks con Tolerancia a Fallos en `jg_agente`:**
   - Crear la función `notify_execution_completion(output: AgentOutput, callback_url: str | None = None) -> bool`.
   - Determinar el destino: prioridad a `callback_url` si fue provista en `AgentInput` o parámetros/metadatos; de lo contrario, utilizar el endpoint canónico del Dashboard: `f"{DASHBOARD_URL}/api/v1/internal/executions/{execution_id}/complete"`.
   - Soporte de fallback automático a `/api/internal/...` si el servidor remoto responde con HTTP 404.
   - Autenticación segura mediante cabeceras `Authorization: Bearer <secret>`, `X-Agent-ID: <id>`, `X-Agent-Secret: <secret>` y `X-Correlation-ID: <cid>`.
   - Política de reintentos con backoff exponencial configurable (`EXECUTION_CALLBACK_MAX_RETRIES`, `EXECUTION_CALLBACK_TIMEOUT_SECONDS`).
   - Captura de cualquier excepción para garantizar que el fallo de red del webhook nunca provoque errores no controlados en el proceso de fondo del agente.

2. **Garantía de Ejecución en `run_in_background`:**
   - Envolver la ejecución en un bloque `try/except/finally`.
   - Si ocurre una excepción no capturada, sintetizar un `AgentOutput` con `status=ExecutionStatus.FAILED` conteniendo la descripción y traza del error.
   - Despachar incondicionalmente la notificación en el bloque `finally`.

3. **Controlador Receptor Interno en `jg_dashboard`:**
   - Implementar `App\Http\Controllers\Api\InternalExecutionController@complete`.
   - Autenticar al agente contra la base de datos validando `hash_equals` de su secreto permanente (`$agent->verifyPermanentSecret()`).
   - Sincronizar o crear el registro correspondiente en `AgentTask` con estado `COMPLETED`, `FAILED` o `WAITING_APPROVAL`, marcas de tiempo `completed_at` y duración.
   - Si la ejecución requiere intervención humana, registrar inmediatamente la solicitud pendiente en `HitlApprovalService`.
   - Registrar la auditoría correspondiente mediante `AuditEvent::record()`.
