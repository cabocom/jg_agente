# Walkthrough Técnico: ISSUE-F08-T03 - Bucle de heartbeat periódico hacia jg_dashboard

## 1. Resumen de Cambios Realizados

### Configuración (`app/core/config.py`)
- Añadidos parámetros de configuración de heartbeat:
  - `ENABLE_HEARTBEAT: bool = True`
  - `HEARTBEAT_INTERVAL_SECONDS: int = 30`
  - `HEARTBEAT_TIMEOUT_SECONDS: float = 5.0`

### Servicio de Latidos (`app/core/heartbeat.py`)
- Implementada la función `collect_system_metrics(start_time, registry)`:
  - Extrae `memory_mb` mediante `resource.getrusage`, adaptando el divisor según la plataforma (1024 en Linux, $1024 \times 1024$ en Darwin/macOS).
  - Calcula `uptime_seconds`.
  - Reporta el recuento de herramientas, plugins y engines activos en el `CapabilityRegistry`.
  - Adjunta `timestamp` en formato UTC ISO 8601 y la versión actual del paquete.
- Implementada la clase `HeartbeatService`:
  - `send_heartbeat()`: Realiza petición POST con timeout configurable y token portador. Tolera 404 mediante reintento al endpoint legado (`/api/agents/heartbeat`). Captura excepciones de transporte de red (`httpx.RequestError`), emite advertencias con `logger.warning()` y actualiza el contador de fallos.
  - `run_loop()`: Tarea en bucle asíncrono con `asyncio.sleep()` que invoca `send_heartbeat()` periódicamente.
  - `start()` / `stop()`: Métodos de gestión de la tarea en segundo plano con cancelación segura (`with contextlib.suppress(asyncio.CancelledError)`).

### Integración en el Ciclo de Vida (`app/main.py`)
- En el arranque (`lifespan`): Se crea e inicia `HeartbeatService` si `settings.ENABLE_HEARTBEAT` está activo y existe `PERMANENT_AGENT_SECRET`.
- En la finalización: Se detiene la tarea mediante `await heartbeat_service.stop()`.
- Endpoint `GET /`: Informa del estado `"heartbeat_active"` y `"last_heartbeat_at"`.

## 2. Validación y Verificación
- Suite de pruebas completa en `tests/test_heartbeat_service.py`:
  - `test_collect_system_metrics`: Valida la recopilación de métricas y la normalización de memoria.
  - `test_send_heartbeat_success`: Valida respuesta HTTP 200 y registro de marca temporal.
  - `test_send_heartbeat_fallback_404`: Valida el mecanismo de fallback cuando el endpoint v1 devuelve 404.
  - `test_send_heartbeat_network_error_resilience`: Valida que los errores de red (timeout/conexión) no rompen el flujo y se registran como warnings.
  - `test_send_heartbeat_unauthorized_401`: Valida el tratamiento de revocación o rechazo de credenciales.
  - `test_heartbeat_service_start_and_stop_lifecycle`: Valida la creación, ejecución y detención limpia de la tarea en segundo plano.
- Ejecución limpia de linters y verificadores estáticos: Ruff, MyPy estricto y Pytest.
