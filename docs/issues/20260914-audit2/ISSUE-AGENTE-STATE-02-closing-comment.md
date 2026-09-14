# Cierre de Issue: [AGENTE-STATE-02] Degradación Silenciosa de DualPostgresSaver a Memoria y Fuga de Conexiones

## Resolución
Se ha resuelto satisfactoriamente la degradación silenciosa del checkpointer y la fuga de descriptores de conexión en `jg_agente` (Work item [#71](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/71)):

1. **Reintentos con Backoff Exponencial y Alarma Crítica:**
   - La factoría `get_checkpointer()` reintenta hasta 3 veces (configurable con `CHECKPOINT_MAX_RETRIES` y `CHECKPOINT_RETRY_BACKOFF_SECONDS`) la conexión a PostgreSQL con pausas progresivas ante fallos transitorios de red o arranque de contenedores.
   - Si no se logra conectar tras agotar los intentos, se emite una alerta `logger.critical(...)` notificando la falta de persistencia para HITL y checkpoints, y la instancia de contingencia en memoria se marca con `is_degraded = True`.

2. **Detección Activa y Fallo en Healthcheck:**
   - El endpoint `GET /health` inspecciona el estado del checkpointer activo.
   - Si `CHECKPOINT_SAVER="postgres"` y el checkpointer está degradado o no conectado, el servicio responde con **HTTP 503 Service Unavailable** y `status="unhealthy"`, haciendo fallar inmediatamente el `HEALTHCHECK` nativo de Docker para que el orquestador detecte la indisponibilidad.

3. **Gestión del Ciclo de Vida y Prevención de Fugas:**
   - Se implementó el método `close()` en `DualPostgresSaver` y la función `close_checkpointer()` para cerrar limpiamente el `ConnectionPool` (`psycopg_pool`).
   - El lifespan de FastAPI en `app/main.py` almacena la instancia en `app.state.checkpointer` durante el arranque y la cierra explícitamente durante el `shutdown`.
   - Se protege la inicialización en `get_postgres_checkpointer` cerrando el pool si falla la creación de esquemas o vistas.

4. **Verificación:**
   - Pruebas unitarias añadidas en `tests/test_checkpointer.py` y `tests/test_api_telemetry.py`.
   - Verificación estática completa con `ruff check`, `ruff format --check` y `mypy app tests plugins` 100% limpia.
   - Verificación global ejecutada con `bash check_unit.sh` (415 pruebas de `jg_agente` y 263 pruebas de `jg_dashboard` pasadas exitosamente).
