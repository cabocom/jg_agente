# 06. Referencia de API REST Privada (`jg_agente`)

[← Volver al README](../README.md) | [← 05. Plugins](05_plugin_lifecycle.md) | [07. Modos de Funcionamiento →](07_operational_modes.md)

---

Todos los endpoints de ejecución y control requieren autenticación criptográfica inter-servicio (`verify_control_plane_auth`) mediante firma HMAC-SHA256 por parte del emisor o invocador externo (Bots de Telegram/WhatsApp, API Gateways, microservicios clientes o consolas de control como `jg_dashboard`). Los endpoints de telemetría de salud y métricas son de libre consulta interna en la red privada.

---

## 1. Endpoints de Ejecución (`/executions`)

### `POST /executions/trigger`
Dispara o continúa la ejecución del grafo cognitivo para una solicitud dada.

- **Cabeceras obligatorias:**
  - `X-Signature`: Firma HMAC-SHA256 del cuerpo y ruta (`/executions/trigger`).
  - `X-Timestamp`: Epoch UNIX en segundos (tolerancia máxima de 300 segundos).
  - `X-Agent-ID`: Identificador único del agente destinatario.
  - `X-Correlation-ID`: Identificador de traza distribuida (opcional pero recomendado; si no se envía, el middleware genera uno nuevo).
- **Parámetros de consulta (Query Params):**
  - `sync` (boolean, default `true`): Si es `false`, la tarea se despacha en segundo plano (vía `BackgroundTasks` de FastAPI) devolviendo inmediatamente `202 Accepted` y notificando el resultado al webhook configurado (`callback_url` o Dashboard).
- **Cuerpo de Solicitud (`AgentInput`):**
  Soporta alias semánticos para facilitar la integración con ecosistemas de mensajería:
  - `thread_id` (alias aceptado: `session_id`).
  - `prompt` (alias aceptado: `message`).
  ```json
  {
    "execution_id": "exec-9a7c3b21-...",
    "thread_id": "th-4b8e2109-...",
    "prompt": "Consultar temperatura en Madrid y verificar alertas",
    "parameters": {},
    "user_context": {
      "user_id": "usr-1",
      "username": "operador",
      "role": "operator"
    },
    "metadata": {},
    "callback_url": "https://gateway.empresa.com/webhooks/agent-done"
  }
  ```
- **Respuestas:**
  - `200 OK`: Ejecución finalizada con éxito (`AgentOutput`) o pausada en espera de confirmación humana (`requires_approval: true`, `status: WAITING_APPROVAL`).
  - `202 Accepted`: Ejecución encolada en segundo plano de forma asíncrona.
  - `401 Unauthorized`: Firma HMAC inválida, cabeceras ausentes o timestamp desfasado (>300s).
  - `422 Unprocessable Entity`: Error de validación en el esquema `AgentInput`.
  - `500 Internal Server Error`: Fallo interno durante la ejecución del grafo.

---

### `GET /executions/{thread_id}`
Recupera el estado operacional completo, el snapshot del checkpointer de LangGraph, la traza de nodos recorridos y el historial de pasos cognitivos para una sesión determinada.

- **Esquema de Respuesta (`ExecutionThreadDetail`):**
  ```json
  {
    "thread_id": "th-4b8e2109-...",
    "execution_id": "exec-9a7c3b21-...",
    "correlation_id": "c01824a7-b28e-49b8-b570-5bfa17cb1212",
    "status": "waiting_approval",
    "prompt": "Reiniciar servicio de base de datos en producción",
    "response": "Operación de alto riesgo detenida. Requiere confirmación humana.",
    "current_step": 3,
    "next_nodes": ["human_approval"],
    "plan": {
      "goal": "Reiniciar base de datos",
      "steps": [{"step_id": "s1", "tool_name": "db_restart", "action": "Restart DB"}]
    },
    "steps": [
      {
        "step_id": "s0",
        "tool_name": "db_health",
        "status": "completed",
        "result": {"healthy": false}
      }
    ],
    "cognitive_steps": [
      {"node": "start", "decision": "plan", "timestamp": "2026-10-04T12:00:00Z"},
      {"node": "plan", "decision": "evaluate_safety", "timestamp": "2026-10-04T12:00:01Z"},
      {"node": "evaluate_safety", "decision": "human_approval", "timestamp": "2026-10-04T12:00:02Z"}
    ],
    "approval_status": "pending",
    "requires_approval": true,
    "pending_approval_id": "hitl-9f123a",
    "persistence_metadata": {
      "status": "persisted",
      "persisted": true,
      "error": null,
      "error_type": null
    }
  }
  ```
- **Campos Destacados:**
  - `next_nodes`: Lista de nombres de nodos del grafo LangGraph pendientes de ejecución en el checkpoint actual.
  - `cognitive_steps`: Traza cronológica detallada de cada salto cognitivo y bifurcación evaluada en el grafo.
  - `persistence_metadata`: Información tipada sobre la durabilidad en PostgreSQL (`persisted`, `degraded` o `failed`).
- **Códigos HTTP:**
  - `200 OK`: Detalle recuperado correctamente.
  - `404 Not Found`: Hilo no encontrado ni en base de datos (`core_executions`) ni en el checkpointer.

---

### `POST /executions/{thread_id}/approve`
Reanuda un flujo de ejecución detenido en el nodo `human_approval` (HITL).

- **Cuerpo de Solicitud (`HITLResolutionRequest`, opcional):**
  ```json
  {
    "approver": "operador@empresa.com",
    "notes": "Plan verificado y autorizado"
  }
  ```
- **Respuestas:**
  - `200 OK`: Grafo reanudado mediante `Command(resume=...)`, devolviendo `AgentOutput`.
  - `400 Bad Request`: El hilo no se encuentra en estado de espera de aprobación.
  - `404 Not Found`: Hilo no encontrado en el checkpointer.
  - `409 Conflict`: El hilo ya finalizó previamente.

---

### `POST /executions/{thread_id}/reject`
Cancela un flujo de ejecución detenido en el nodo `human_approval` (HITL).

- **Cuerpo de Solicitud (`HITLResolutionRequest`, opcional):**
  ```json
  {
    "approver": "operador@empresa.com",
    "notes": "Parámetros de mutación inseguros"
  }
  ```
- **Respuestas:**
  - `200 OK`: Grafo cancelado, devolviendo `AgentOutput` con `status="cancelled"`.

---

## 2. Mecanismo de Notificación Webhook Asíncrona (`notify_execution_completion`)

Cuando una ejecución se dispara en modo asíncrono (`POST /executions/trigger?sync=false`), el runtime procesa el grafo en segundo plano y despacha el resultado mediante una llamada HTTP POST saliente:

```text
┌────────────────────────────────────────────────────────┐
│               Finalización de Ejecución Async          │
└──────────────────────────┬─────────────────────────────┘
                           │
                 ¿Se definió callback_url?
                 ├── SÍ ──► Dispara POST a callback_url
                 │
                 └── NO ──► Destino por defecto:
                            {DASHBOARD_URL}/api/v1/internal/executions/{id}/complete
                                  │
                                  ▼
                         ¿Respuesta 404 Not Found?
                         ├── SÍ ──► Reintento transparente a URL legacy:
                         │          {DASHBOARD_URL}/api/internal/executions/{id}/complete
                         └── NO ──► OK
```

### 2.1 Cabeceras de Seguridad Salientes
La petición saliente incluye autenticación de confianza:
- `X-Correlation-ID`: Identificador de traza persistido a lo largo de toda la cadena.
- `X-Agent-ID`: Identificador configurado en `AGENT_ID`.
- `Authorization`: `Bearer {AGENT_SECRET}`.
- `X-Agent-Secret`: Secreto compartido para verificación directa.
- `User-Agent`: `jg_agente/{__version__}`.

### 2.2 Política de Reintentos y Resiliencia
- **Parámetros configurables:**
  - `EXECUTION_CALLBACK_TIMEOUT_SECONDS`: Tiempo máximo de espera por intento (por defecto `5.0` segundos).
  - `EXECUTION_CALLBACK_MAX_RETRIES`: Número máximo de reintentos en caso de error de red o timeout (por defecto `3`).
- **Fallback Automático de Rutas 404:** Si el destinatario por defecto no expone la ruta versionada `/api/v1/...` (por ejemplo, versiones anteriores de `jg_dashboard`), el webhook reintenta inmediatamente contra `/api/...` antes de computar un fallo.

---

## 3. Endpoints de Observabilidad y Telemetría

### `GET /health`
Chequeo de salud asíncrono para Kubernetes / Docker Healthcheck.

- **Respuesta (`200 OK` o `503 Service Unavailable`):**
  ```json
  {
    "status": "healthy",
    "service": "jg_agente",
    "version": "0.1.0",
    "database": "connected",
    "components": {
      "database": {"status": "connected", "latency_ms": 1.2},
      "checkpointer": {"status": "ready", "details": {"type": "PostgresSaver"}},
      "llm": {"status": "ready", "details": {"provider": "groq", "model": "llama-3.3-70b-versatile"}}
    },
    "timestamp": "2026-10-03T18:00:00Z"
  }
  ```

### `GET /metrics`
Métricas agregadas del runtime, latencias observadas y conteos HITL.

- **Respuesta (`200 OK`):**
  ```json
  {
    "service": "jg_agente",
    "version": "0.1.0",
    "uptime_seconds": 3600.5,
    "executions": {
      "total_executions": 142,
      "completed": 135,
      "failed": 2,
      "cancelled": 1,
      "waiting_approval": 4,
      "avg_execution_time_ms": 450.2,
      "min_execution_time_ms": 120.1,
      "max_execution_time_ms": 1820.5
    },
    "capabilities": {
      "tools": 8,
      "engines": 2,
      "plugins": 2
    },
    "hitl": {
      "approvals_requested": 5,
      "approvals_pending": 4
    }
  }
  ```

### `GET /capabilities`
Inventario consolidado de herramientas y motores activos registrados en `CapabilityRegistry`.

---

## 4. Navegación

- [← Anterior: 05. Ciclo de Vida y Ecosistema de Plugins](05_plugin_lifecycle.md)
- [Índice General](../README.md)
- [Siguiente: 07. Modos de Funcionamiento, Topologías y Registro →](07_operational_modes.md)
