# Análisis Técnico: [AGENTE-STATE-01] Persistencia Best-Effort Oculta Pérdida de Ejecuciones en Base de Datos

## 1. Identificación del Problema
- **Issue:** [jg_agente#70] `[AGENTE-STATE-01] Persistencia Best-Effort Oculta Pérdida de Ejecuciones en Base de Datos`
- **Severidad:** 🟠 ALTO
- **Ubicación:** `jg_agente/app/api/executions.py`

## 2. Causa Raíz
En los bloques de persistencia de `execute_graph_pipeline`, `trigger_execution` y `_resolve_hitl_execution`, las llamadas a `_persist_or_update_execution` estaban protegidas por:

```python
try:
    async with async_session_factory() as db:
        await _persist_or_update_execution(...)
    agent_output.metadata["persistence"] = PersistenceMetadata(
        status=PersistenceStatus.PERSISTED,
        persisted=True,
    ).model_dump()
except (PersistenceError, Exception) as db_err:
    agent_output.metadata["persistence"] = PersistenceMetadata(
        status=PersistenceStatus.DEGRADED,
        persisted=False,
        error=str(db_err),
        error_type=type(db_err).__name__,
    ).model_dump()
return agent_output  # HTTP 200 OK
```

Esto provocaba:
1. **Ausencia de Reintentos:** Un fallo transitorio de milisegundos en la conexión o en el pool de PostgreSQL causaba inmediatamente la degradación sin intentar reconectar.
2. **Ocultamiento de Fallos (Silent Data Loss):** El endpoint retornaba HTTP 200 OK con `status = completed`, lo que hacía que el Dashboard considerara la tarea finalizada con éxito sin alertar de que los datos no existían en base de datos.
3. **Connection Starvation en `trigger_execution` (`AGENTE-STATE-03`):** El endpoint inyectaba `db: AsyncSession` que se mantenía abierta durante toda la ejecución síncrona del grafo, consumiendo conexiones del pool de SQLAlchemy.

## 3. Estrategia de Solución
1. **Reintentos con Backoff Exponencial (`_persist_with_retry`):**
   - Función centralizada con bucle de hasta 3 intentos (`settings.PERSISTENCE_MAX_RETRIES`).
   - Backoff exponencial (`settings.PERSISTENCE_RETRY_BACKOFF_SECONDS * 2^attempt`).
   - Adquisición de sesión limpia independiente por cada intento mediante `async_session_factory()`.
2. **Propagación Explícita de Error (HTTP 500):**
   - Si la base de datos no responde tras agotar los reintentos, el endpoint no simula éxito: lanza `HTTPException(status_code=500)` advirtiendo al cliente y al Dashboard de la indisponibilidad de persistencia.
3. **Mecanismo de Respaldo de Emergencia (Spooling Local en Disco):**
   - Antes de lanzar el error HTTP 500, se invoca `_spool_emergency_execution()` para persistir el payload completo (`AgentOutput`, pasos cognitivos, estado) en `data/emergency_executions/<execution_id>.json`.
   - Garantiza que, incluso si la base de datos colapsa, la información de auditoría no se pierde en memoria.
4. **Liberación Inmediata de Sesión en `trigger_execution`:**
   - Desacoplamiento de la dependencia `db` en la firma de `trigger_execution`, resolviendo el acaparamiento prolongado de conexiones.
