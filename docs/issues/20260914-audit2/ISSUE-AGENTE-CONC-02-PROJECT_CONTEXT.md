# Contexto del Proyecto: [AGENTE-CONC-02] Pérdida de Trazabilidad y Notificaciones en Tareas Asíncronas en Background

## Descripción del Entorno
- **Componentes Afectados:**
  - `jg_agente` (Execution Plane): `app/api/executions.py`, `app/core/config.py`, `app/models/io.py`
  - `jg_dashboard` (Control Plane): `app/Http/Controllers/Api/InternalExecutionController.php`, `routes/api.php`
- **Severidad:** 🟡 MEDIO
- **Protocolo de Comunicación:** Webhook HTTP asíncrono con autenticación de credenciales de agente (`X-Agent-ID`, `Bearer <secret>`).

## Contexto Operativo
`jg_agente` permite disparar ejecuciones cognitivas tanto en modo síncrono (`sync=True`, HTTP 200 OK) como asíncrono (`sync=False` o `parameters.async=True`, HTTP 202 Accepted).
En modo asíncrono, la solicitud HTTP responde de inmediato al llamador liberando la conexión de red, mientras la ejecución real del grafo de LangGraph se delega a `BackgroundTasks` de FastAPI mediante la función `run_in_background(graph, input_data)`.

En el Control Plane (`jg_dashboard`), al disparar una ejecución asíncrona, se crea un registro `AgentTask` en base de datos con estado inicial `QUEUED` o `PROCESSING`.

## Problema Detectado
En la implementación previa:
1. La corrutina `run_in_background(graph, input_data)` invocaba `execute_graph_pipeline(graph, input_data)` sin ningún mecanismo de notificación o callback de salida.
2. Si el grafo finalizaba con éxito (`COMPLETED`), se detenía en un punto de aprobación humana (`WAITING_APPROVAL`) o fallaba por excepción no controlada (`FAILED`):
   - El resultado quedaba únicamente registrado en la base de datos interna de `jg_agente` (`core_executions`).
   - El Dashboard no recibía ningún aviso ni evento de finalización.
3. Esto obligaba al Dashboard a implementar sondeos continuos a ciegas (blind polling) sobre `GET /executions/{agent_id}/{thread_id}` o provocaba que las tareas asíncronas quedasen indefinidamente congeladas como `QUEUED` en las interfaces de usuario de Filament y la consola web si el operador no recargaba manualmente.
