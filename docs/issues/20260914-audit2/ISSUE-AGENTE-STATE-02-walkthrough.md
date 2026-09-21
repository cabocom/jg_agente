# Walkthrough Técnico: [AGENTE-STATE-02] Degradación Silenciosa de DualPostgresSaver a Memoria y Fuga de Conexiones

## Resumen de Cambios Aplicados

### 1. Configuración Centralizada ([`app/core/config.py`](../../../app/core/config.py))
- Se declararon explícitamente las variables de configuración del checkpointer en `Settings`:
  - `CHECKPOINT_SAVER: str = "postgres"`
  - `CHECKPOINT_MAX_RETRIES: int = 3` (ge=1)
  - `CHECKPOINT_RETRY_BACKOFF_SECONDS: float = 0.5` (ge=0.01)

### 2. Ciclo de Vida y Reintentos del Checkpointer ([`app/core/checkpointer.py`](../../../app/core/checkpointer.py))
- **Método `.close()` en `DualPostgresSaver`:** Cierra de forma idempotente y segura el `ConnectionPool` subyacente (`self.conn.close()`), registrando el evento en logs.
- **Función `close_checkpointer(saver: Any)`:** Invoca `close()` si el objeto lo implementa, tolerando `None` o `MemorySaver` sin fallos.
- **Protección en `get_postgres_checkpointer`:** En caso de excepción durante `saver.setup()` o creación de vistas `core_checkpoints`, se invoca `saver.close()` antes de re-lanzar la excepción para evitar fuga de pools huérfanos.
- **Bucle de reintentos con backoff exponencial en `get_checkpointer`:**
  - Aplica hasta `CHECKPOINT_MAX_RETRIES` intentos espaciados por `base_backoff * (2 ** (attempt - 1))`.
  - Ante fallo final, emite `logger.critical(...)` notificando que el agente operará en modo degradado sin persistencia durable para HITL y checkpoints.
  - La instancia fallback de `MemorySaver` queda marcada con `is_degraded = True` y `degraded_reason = str(last_exc)`.

### 3. Ciclo de Vida de FastAPI ([`app/main.py`](../../../app/main.py))
- En el arranque (`startup` de `lifespan`): Se inicializa y almacena la instancia de checkpointer en `app.state.checkpointer = get_checkpointer()`.
- En el apagado (`shutdown` de `lifespan`): Se invoca explícitamente `close_checkpointer(getattr(app.state, "checkpointer", None))`, garantizando la liberación inmediata de conexiones en PostgreSQL.

### 4. Detección y Fallo en Healthcheck ([`app/api/telemetry.py`](../../../app/api/telemetry.py))
- El endpoint `GET /health` evalúa el checkpointer activo (`request.app.state.checkpointer`).
- Si `CHECKPOINT_SAVER="postgres"` y el checkpointer está degradado a memoria o no pudo conectar, se reporta `components.checkpointer.status = "degraded"` y `global_status = "unhealthy"`.
- En caso de desconexión o degradación, la respuesta HTTP se emite con **HTTP 503 Service Unavailable**, provocando el fallo del `HEALTHCHECK` nativo de Docker.

### 5. Suite de Pruebas Unitarias
- [`tests/test_checkpointer.py`](../../../tests/test_checkpointer.py):
  - `test_dual_postgres_saver_close`: Cierre del pool e idempotencia.
  - `test_close_checkpointer_helper`: Invocación segura y compatibilidad con `None` / `MemorySaver`.
  - `test_get_checkpointer_retries_and_degrades_to_memory`: Verifica 3 intentos con pausas de 0.1s y 0.2s, log CRITICAL y atributos `is_degraded = True`.
  - `test_get_checkpointer_recovers_on_retry`: Verifica recuperación en intento transitorio.
- [`tests/test_api_telemetry.py`](../../../tests/test_api_telemetry.py):
  - `test_get_health_unhealthy_on_database_error`: Verifica respuesta HTTP 503 y `status="unhealthy"` ante caída de PostgreSQL.
  - `test_get_health_unhealthy_when_checkpointer_degraded`: Verifica respuesta HTTP 503 y componente degradado cuando falla el checkpointer PostgreSQL.
