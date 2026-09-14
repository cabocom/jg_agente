# Cierre de Issue: [AGENTE-STATE-03] Doble Sesión de Base de Datos Concurrente por Request Saturation Pool

## Resolución
Se ha resuelto satisfactoriamente la doble sesión concurrente y la retención ociosa de conexiones en el pool de PostgreSQL de `jg_agente` (Work item [#72](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/72)):

1. **Eliminación de Sesiones Residuales en Rutas de Larga Duración:**
   - Se removió la inyección de dependencias `db: AsyncSession = Depends(get_async_session)` en todos los endpoints de ejecución y reanudación/cancelación HITL:
     - `POST /executions/trigger`
     - `POST /executions/{thread_id}/approve`
     - `POST /executions/{thread_id}/reject`
     - `POST /executions/approve`
     - `POST /executions/reject`
     - Función interna `_resolve_hitl_execution`.

2. **Gestión Atómica de Sesiones Scoped:**
   - La persistencia relacional en `core_executions` se delega exclusivamente a `_persist_with_retry()`, la cual utiliza context managers efímeros `async with async_session_factory() as db:`.
   - Las conexiones solo se solicitan al pool en el instante exacto de guardar o actualizar el registro (<5ms) y se devuelven inmediatamente, evitando saturación del pool durante el razonamiento cognitivo y la ejecución de tools.

3. **Verificación y Pruebas:**
   - Creada la suite `tests/test_session_pool_saturation.py` validando por introspección de dependencias que ningún endpoint de ejecución retenga `get_async_session`.
   - Validada la suite de ejecución completa (`test_api_executions_trigger.py`, `test_api_executions_get.py`, `test_persistence_propagation.py`).
   - Verificación estática con `ruff` y `mypy` (108 archivos verificados, 0 errores).
   - Verificación global con `bash check_unit.sh` (417 pruebas de `jg_agente` y 263 pruebas de `jg_dashboard` pasadas exitosamente).
