### Resolución de [ISSUE-AGENT-006] Semántica y propagación de errores en persistencia de ejecuciones (GitLab #47)

Se ha completado la resolución del issue AGENT-006 eliminando el silenciamiento ciego de errores de base de datos e introduciendo observabilidad tipada de degradación en el Execution Plane:

1. **Eliminación del Silenciamiento Ciego en `_persist_or_update_execution`:**
   - La función ya no captura genéricamente con retorno `None`. Realiza `await db.rollback()`, emite logs estructurados con severidad `ERROR` (`logger.error`) y eleva la excepción tipada `PersistenceError`.

2. **Modelos Tipados de Degradación (`app/models/io.py`):**
   - Se crearon `PersistenceStatus` y `PersistenceMetadata` (`persisted`, `error`, `error_type`, `status`).
   - Se inyectan en `AgentOutput.metadata["persistence"]` en todas las ramas de ejecución (`execute_graph_pipeline`, `trigger_execution`, `_resolve_hitl_execution`).
   - Si la base de datos es inaccesible, el ciclo del agente preserva su resiliencia en memoria devolviendo el resultado pero exponiendo de forma transparente y verificable `status: "degraded"`.

3. **Verificación y Pruebas:**
   - Se añadieron 6 pruebas unitarias específicas en `tests/test_persistence_propagation.py`.
   - La suite completa de `jg_agente` supera todas las verificaciones (`scripts/check.sh` conforme en Ruff, MyPy estricto y Pytest con 338/338 tests pasados al 100%).

/close
