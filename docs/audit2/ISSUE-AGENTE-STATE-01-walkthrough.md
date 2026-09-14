# Walkthrough: [AGENTE-STATE-01] Persistencia Best-Effort Oculta Pérdida de Ejecuciones en Base de Datos

## Resumen de Cambios

### 1. Configuración de Persistencia y Spooling (`app/core/config.py`)
- Incorporadas variables:
  - `PERSISTENCE_MAX_RETRIES` (por defecto `3`).
  - `PERSISTENCE_RETRY_BACKOFF_SECONDS` (por defecto `0.2`s).
  - `EMERGENCY_PERSISTENCE_DIR` (por defecto `"data/emergency_executions"`).

### 2. Motor de Reintentos y Spooling de Emergencia (`app/api/executions.py`)
- Implementado `_persist_with_retry()`: reintenta hasta 3 veces con pausas exponenciales creando sesiones limpias en cada intento.
- Implementado `_spool_emergency_execution()`: vuelca el estado y saltos cognitivos a disco local en formato JSON ante fallo definitivo de base de datos.
- Reemplazados los bloques degradados por elevación controlada de `HTTPException(status_code=500)` en:
  - `execute_graph_pipeline`: finalización exitosa, pausas HITL e interrupciones.
  - `trigger_execution`: registro inicial preventivo.
  - `_resolve_hitl_execution`: aprobación o rechazo de solicitudes HITL.
- Eliminada la inyección de larga duración `db: AsyncSession` en `trigger_execution`.

### 3. Aislamiento y Suite de Pruebas (`tests/test_persistence_propagation.py` y `tests/conftest.py`)
- `tests/test_persistence_propagation.py`:
  - `test_persist_with_retry_transient_failure_recovery`: valida recuperación automática ante fallo transitorio en intento 1.
  - `test_persist_with_retry_fatal_failure_raises_persistence_error`: valida elevación de `PersistenceError` tras agotar los 3 intentos.
  - `test_spool_emergency_execution`: valida creación del fichero JSON de respaldo en disco.
  - `test_execute_graph_pipeline_fatal_persistence_failure_spools_and_raises_500`: valida volcado y respuesta HTTP 500 ante fallo definitivo.
  - `test_trigger_execution_fatal_persistence_failure_returns_500`: valida que `/executions/trigger` no oculta la caída de DB.
  - `test_resolve_hitl_execution_fatal_persistence_failure_raises_500`: valida respuesta 500 en resolución HITL.
- `tests/conftest.py`: fixture `mock_persistence_for_unit_tests` para aislar pruebas unitarias generales sin requerir instancia física de PostgreSQL.

---

## Verificación Automatizada

```bash
$ bash check_unit.sh
==================================================================
📊 RESUMEN DE PRUEBAS UNITARIAS
==================================================================
  ✅ jg_agente:    PASÓ (Ruff, MyPy y Pytest correctos)
  ✅ jg_dashboard: PASÓ (Pest y pruebas PHP correctas)
==================================================================
🎉 ¡TODOS LOS TESTS UNITARIOS SE HAN EJECUTADO CORRECTAMENTE!
==================================================================
```
