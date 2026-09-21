# Walkthrough: [ISSUE-AGENT-006] Semántica y propagación de errores en persistencia de ejecuciones

## 1. Resumen de Cambios

### Capa de Persistencia y Modelos
- **[app/db/exceptions.py](../../../app/db/exceptions.py)**:
  - Definición de la excepción tipada `PersistenceError`.
- **[app/db/__init__.py](../../../app/db/__init__.py)**:
  - Exportación de `PersistenceError` en la API pública del módulo `app.db`.
- **[app/models/io.py](../../../app/models/io.py)**:
  - Incorporación de `PersistenceStatus` (`PERSISTED`, `DEGRADED`, `FAILED`).
  - Incorporación del modelo de metadatos `PersistenceMetadata`.
- **[app/models/__init__.py](../../../app/models/__init__.py)**:
  - Exportación de `PersistenceStatus` y `PersistenceMetadata`.

### Capa de Control y Orquestación de Ejecuciones
- **[app/api/executions.py](../../../app/api/executions.py)**:
  - `_persist_or_update_execution`: Reemplazo del bloque `except Exception: return None` por captura explícita, `await db.rollback()`, logging con severidad `ERROR` y propagación de `PersistenceError`.
  - `execute_graph_pipeline`: Captura de `PersistenceError` y asignación tipada en `agent_output.metadata["persistence"]` en los caminos de éxito, pausa HITL y excepciones no controladas. Eliminación de `except Exception: pass`.
  - `trigger_execution`: Captura y registro del estado inicial de persistencia en `input_data.metadata["persistence"]`.
  - `_resolve_hitl_execution`: Propagación de metadatos tipados y registro `ERROR` ante fallos durante la confirmación o rechazo de una pausa HITL.

### Suite de Pruebas
- **[tests/test_persistence_propagation.py](../../../tests/test_persistence_propagation.py)**:
  - Verificación de persistencia exitosa y refresco en base de datos.
  - Verificación de que `_persist_or_update_execution` eleva `PersistenceError` y efectúa rollback.
  - Verificación de metadatos con `status="persisted"` en ejecuciones exitosas.
  - Verificación de tolerancia a fallos y propagación de `status="degraded"` en `execute_graph_pipeline`.
  - Verificación del endpoint `POST /executions/trigger` ante fallo inicial de base de datos.
  - Verificación de resolución HITL con persistencia degradada.

## 2. Verificación Automatizada

### Pruebas Unitarias Dedicadas
```bash
.venv/bin/pytest tests/test_persistence_propagation.py -v
```
Resultado: 6 passed (100%).

### Verificación Integral (`scripts/check.sh`)
- **Ruff:** 100 archivos formateados y linter sin advertencias.
- **MyPy:** Chequeo estricto superado en 100 archivos fuente.
- **Pytest:** 338 tests pasados al 100%.
