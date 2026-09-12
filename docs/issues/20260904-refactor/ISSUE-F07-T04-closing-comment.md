### Resumen de Implementación — ISSUE-F07-T04

Se ha completado la implementación de los endpoints REST de telemetría, salud y observabilidad (`GET /capabilities`, `GET /health` y `GET /metrics`) en `jg_agente`, permitiendo al plano de control (`jg_dashboard`) y a los sistemas de monitorización inspeccionar en tiempo real el inventario de capacidades cargadas, el estado de conectividad con PostgreSQL y LLM, y las métricas de rendimiento y ejecución.

#### 1. Componentes Desarrollados y Modificados
- **`app/models/io.py` & `app/models/__init__.py`:**
  - Modelos de telemetría Pydantic fuertemente tipados:
    - `HealthComponentStatus`: estado individual de cada subsistema (`status`, `latency_ms`, `details`, `error`).
    - `HealthResponse`: respuesta normalizada de salud global (`status`, `service`, `version`, `database`, `components`, `timestamp`).
    - `ExecutionMetrics`: desglose cuantitativo de ejecuciones (`total_executions`, `completed`, `failed`, `cancelled`, `waiting_approval`, `in_progress`, `avg_execution_time_ms`, `min_execution_time_ms`, `max_execution_time_ms`).
    - `MetricsResponse`: respuesta consolidada con `uptime_seconds`, estadísticas de ejecución, capacidades activas y conteos HITL.
- **`app/core/registry.py`:**
  - Ampliación de `get_capabilities_summary()` para enriquecer el catálogo de herramientas con `description` y la directiva de compensación `reversible`.
- **`app/api/telemetry.py`:**
  - `GET /capabilities`: expone el catálogo estructurado de plugins, herramientas (con categoría, nivel de riesgo, reversibilidad y permisos) y motores cognitivos registrados en `CapabilityRegistry`.
  - `GET /health`: chequeo asíncrono activo contra PostgreSQL (`SELECT 1`), cálculo de latencia de sondeo en milisegundos, e inspección del proveedor LLM y tipo de checkpointer configurado. Resiliente ante fallos de conexión marcando estado `degraded` y `database=disconnected` sin lanzar errores 500 no controlados.
  - `GET /metrics`: cálculo y agregación cuantitativa directa sobre la tabla `core_executions` (`COUNT`, `AVG`, `MIN`, `MAX`), distribución por estado (`completed`, `failed`, `cancelled`, `waiting_approval`, `in_progress`), estadísticas de solicitudes HITL pendientes y capacidades activas. Resiliente ante desconexiones de base de datos.
- **`app/main.py`:**
  - Montaje modular de `telemetry_router` bajo `app.include_router(telemetry_router)`.
  - Limpieza de endpoints legacy inline, desacoplando la capa HTTP hacia `app/api`.
- **`tests/test_api_telemetry.py`:**
  - Suite integral con 5 pruebas unitarias y de integración que validan:
    1. `GET /capabilities`: catálogo completo con códigos 200, conteo y metadata de tools/engines/plugins.
    2. `GET /health` (Healthy): verificación de subsistemas (database, llm, checkpointer) y latencia observada.
    3. `GET /health` (Degraded): tolerancia a caídas de PostgreSQL sin abortar la API (200 con status degraded).
    4. `GET /metrics` (Aggregated): agregación de métricas de ejecución, tiempos medios/mínimos/máximos y flujo HITL.
    5. `GET /metrics` (Resilience): comportamiento seguro y métricas iniciales limpias ante caídas de base de datos.

#### 2. Validación y Métricas de Calidad
- `./scripts/check.sh`: **100% verde**.
  - **Ruff:** Linter y formato conformes en los 66 archivos del proyecto.
  - **MyPy:** Modo estricto sin errores en los 66 archivos.
  - **Pytest:** 218 pruebas unitarias e integradas pasando en 1.00 segundos.

#### 3. Cumplimiento de Criterios de Aceptación
- [x] **GET /capabilities:** Devuelve estado 200 con listado completo de tools y engines activos.
- [x] **GET /health:** Devuelve estado 200 con verificación activa de conexión a PostgreSQL y estado del LLM.
- [x] **GET /metrics:** Devuelve estado 200 con tiempos promedio de ejecución, desglose de estados y métricas HITL.

/close
