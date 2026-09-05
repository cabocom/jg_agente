### Resumen de Implementación — ISSUE-F07-T01

Se ha completado la implementación del endpoint REST `POST /executions/trigger` en `jg_agente`, permitiendo al plano de control (`jg_dashboard`) o clientes autorizados activar o continuar ejecuciones cognitivas sobre el runtime LangGraph de forma síncrona o asíncrona, con soporte nativo para pausas HITL y persistencia en `core_executions`.

#### 1. Componentes Desarrollados y Modificados
- **`app/api/executions.py` & `app/api/__init__.py`:**
  - Endpoint `POST /executions/trigger` con validación Pydantic basada en `AgentInput` y respuesta canónica `AgentOutput`.
  - Soporte de ejecución síncrona (por defecto o `sync=True`): ejecuta el pipeline LangGraph y responde HTTP 200 con `AgentOutput` final (`status=completed` o `status=failed`).
  - Soporte de ejecución asíncrona (`sync=False` o parámetro `"async": True` / `"background": True`): encola la ejecución en `BackgroundTasks` y responde inmediatamente HTTP 202 Accepted con `status=in_progress`.
  - Captura y adaptación transparente de interrupciones HITL (`GraphInterrupt` o valor `__interrupt__` en estado): devuelve HTTP 200 con `status=waiting_approval`, `requires_approval=True` y `pending_approval_id`.
  - Función de persistencia segura `_persist_or_update_execution` sobre la tabla `core_executions` (`CoreExecution`), registrando estados iniciales, métricas de tiempo (`execution_time_ms`), resultados intermedios y errores, con resiliencia y tolerancia a caídas de conexión.
  - Inyección de dependencias modular vía `Depends(get_agent_graph)` permitiendo testabilidad limpia mediante `dependency_overrides`.
- **`app/main.py`:**
  - Montaje de `executions_router` en la aplicación principal FastAPI.
- **`app/core/graph.py`:**
  - Ajuste en `route_after_reason` y topología de `GraphBuilder` para permitir el enrutamiento directo hacia `risk_assess` ante tool calls en agentes sin motor planificador registrado.
- **`pyproject.toml`:**
  - Configuración de ignorado de regla `B008` en Ruff para admitir llamadas a `Depends(...)` en argumentos de FastAPI.
- **`tests/test_api_executions_trigger.py`:**
  - Suite de 6 tests de integración HTTP validando:
    1. Ejecución síncrona exitosa (HTTP 200, status `completed`).
    2. Ejecución con invocación de herramienta autorizada (HTTP 200, `steps_count=1`).
    3. Interrupción HITL ante acción peligrosa (HTTP 200, status `waiting_approval`, `requires_approval=True`).
    4. Ejecución asíncrona vía query param `?sync=false` (HTTP 202 Accepted, status `in_progress`).
    5. Ejecución asíncrona vía payload JSON `parameters={"async": True}` (HTTP 202 Accepted).
    6. Validación de esquema con payload inválido (HTTP 422 Unprocessable Entity).

#### 2. Validación y Métricas de Calidad
- `./scripts/check.sh`: **100% verde**.
  - **Ruff:** Linter y formateo conformes en los 61 archivos de código.
  - **MyPy:** Tipado estático estricto superado sin errores en los 61 archivos.
  - **Pytest:** 202 pruebas unitarias e integradas pasando en 1.15 segundos.

#### 3. Cumplimiento de Criterios de Aceptación
- [x] **Recepción de payload AgentInput válido:** Validación rigurosa con Pydantic V2.
- [x] **Ejecución síncrona y respuesta 200:** Retorna `AgentOutput` completo con tiempos de ejecución calculados.
- [x] **Ejecución asíncrona y respuesta 202:** Retorna inmediatamente `AgentOutput` con `status=in_progress` y procesa en segundo plano.
- [x] **Gestión de pausa HITL:** Interrupciones capturadas con `status=waiting_approval` sin fallar el proceso.
- [x] **Persistencia en `core_executions`:** Registro y actualización de estado en PostgreSQL.

/close
