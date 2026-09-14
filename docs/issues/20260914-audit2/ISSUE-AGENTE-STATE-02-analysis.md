# Análisis de Causa Raíz: [AGENTE-STATE-02] Degradación Silenciosa de DualPostgresSaver a Memoria y Fuga de Conexiones

## Diagnóstico Técnico
1. **Fallback Prematuro y Falta de Reintentos:**
   En `app/core/checkpointer.py`, la factoría `get_checkpointer()` evaluaba `saver_type` o la variable `CHECKPOINT_SAVER`. Si el valor era `postgres`, llamaba a `get_postgres_checkpointer()`. Ante cualquier excepción (`psycopg.OperationalError`, timeout de socket, etc.), la capturaba y retornaba inmediatamente `get_memory_checkpointer()`.
   No existía ningún bucle de reintento ni pausa exponencial para tolerar el arranque asíncrono habitual de servicios bajo `docker-compose`.

2. **Carencia de Alertas Críticas y Enmascaramiento en Telemetría:**
   La captura de la excepción solo emitía `logger.warning`.
   En `app/api/telemetry.py`, el endpoint `/health` inspeccionaba únicamente la variable `CHECKPOINT_SAVER`, asumiendo siempre `status="ready"` para el checkpointer, ignorando si la instancia activa era en realidad un `MemorySaver` degradado. Como resultado, `/health` devolvía HTTP 200 OK. Docker Healthcheck (`python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"`) consideraba el servicio saludable, impidiendo que el orquestador detectase la falta de persistencia.

3. **Ciclo de Vida sin Cierre de Pools (Resource Leaks):**
   `DualPostgresSaver` encapsula un `psycopg_pool.ConnectionPool`. Dicho pool mantiene sockets TCP abiertos hacia el servidor PostgreSQL.
   Al detener el servicio (`docker stop` o `SIGTERM`), el lifespan de FastAPI en `app/main.py` detenía los plugins y el servicio de heartbeat, pero nunca invocaba el cierre del checkpointer.
   Esto causaba descriptores de socket huérfanos y conexiones inactivas en el backend de PostgreSQL hasta que se cumplía el timeout del servidor.

## Estrategia de Solución
1. **Reintentos con Backoff Exponencial:**
   Configurar `CHECKPOINT_MAX_RETRIES` (3) y `CHECKPOINT_RETRY_BACKOFF_SECONDS` (0.5s) en `Settings`.
   Reintentar la inicialización de `DualPostgresSaver` con pausas progresivas (0.5s, 1.0s).
   Si tras agotar los reintentos la conexión sigue fallando, emitir `logger.critical(...)` con detalle del fallo y marcar la instancia `MemorySaver` retornada con `is_degraded = True` y `degraded_reason`.
2. **Elevación a Falla en `/health` (HTTP 503):**
   Inspeccionar en `/health` tanto la salud de la BD como el estado del checkpointer activo.
   Si `CHECKPOINT_SAVER="postgres"` y el checkpointer está degradado o desconectado, reportar `status="unhealthy"` y emitir un código de respuesta **HTTP 503 Service Unavailable**, haciendo fallar activamente el `HEALTHCHECK` de Docker.
3. **Cierre Explícito en Lifespan:**
   Añadir método `.close()` en `DualPostgresSaver` y función utilitaria `close_checkpointer()`.
   En `app/main.py`, almacenar el checkpointer en `app.state.checkpointer` durante el arranque y cerrarlo explícitamente en el bloque de shutdown.
