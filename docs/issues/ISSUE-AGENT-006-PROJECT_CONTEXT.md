# Contexto de Proyecto: [ISSUE-AGENT-006] Semántica y propagación de errores en persistencia de ejecuciones

## 1. Identificación y Estado
- **Issue ID:** ISSUE-AGENT-006
- **GitLab Item:** #47 (jg_agente)
- **Vínculo Auditoría:** AGENT-006
- **Fase:** Fase Post-Auditoría (Implementación de Hallazgos Codex)
- **Prioridad:** Medium / Observability & Architecture
- **Complejidad Estimada:** M
- **Estado:** Implementado / Verificado

## 2. Alineación Arquitectónica
En la auditoría técnica independiente (hallazgo AGENT-006), se constató que la función central de persistencia `_persist_or_update_execution` (`app/api/executions.py:63-148`) capturaba genéricamente cualquier excepción con un bloque ciego `except Exception`, emitiendo únicamente un log de advertencia (`logger.warning`) y retornando `None`. De forma análoga, los puntos de llamada en el pipeline (`execute_graph_pipeline`, `trigger_execution`, `_resolve_hitl_execution`) utilizaban `logger.warning` o bloques vacíos `except Exception: pass`.

Este comportamiento introducía riesgos severos de consistencia e integridad en el sistema:
1. **Falsos Positivos de Persistencia:** Clientes de la API o el plano de control (`jg_dashboard`) recibían respuestas HTTP `200 OK` con un `AgentOutput` completo, desconociendo por completo que la base de datos `core_executions` había fallado y que la ejecución no disponía de trazabilidad durable.
2. **Invisibilidad Operacional:** La degradación de la persistencia se ocultaba bajo logs de severidad `WARNING` o se suprimía sin registro, imposibilitando que herramientas de monitorización y alertas (Sentry, Prometheus, CloudWatch) detectaran desconexiones con PostgreSQL o fallos transaccionales.

Para corregir esta deficiencia arquitectónica sin comprometer la resiliencia en memoria del agente:
1. **Eliminación del Silenciamiento Ciego:**
   - Se rediseñó `_persist_or_update_execution` para ejecutar `await db.rollback()`, registrar el fallo con nivel **`ERROR`** (incluyendo `exc_info=True`) y elevar una excepción tipada `PersistenceError` (`app.db.exceptions.PersistenceError`).
2. **Modelos Tipados de Degradación (`app/models/io.py`):**
   - Se introdujeron `PersistenceStatus` (`PERSISTED`, `DEGRADED`, `FAILED`) y `PersistenceMetadata` con campos `status`, `persisted: bool`, `error: str | None` y `error_type: str | None`.
3. **Propagación Controlada en el Ciclo de Ejecución:**
   - En `execute_graph_pipeline`, `trigger_execution` y `_resolve_hitl_execution`, las capturas de `PersistenceError` registran el error con nivel `ERROR` y adjuntan de manera determinista `PersistenceMetadata` en `AgentOutput.metadata["persistence"]`.
   - Si la base de datos está disponible, se emite `status="persisted"` (`persisted=True`).
   - Si la persistencia falla, se emite `status="degraded"` (`persisted=False`, con detalles del error y su tipo), garantizando que el plano de control y los consumidores de la API conozcan explícitamente el estado de almacenamiento durable sin tumbar el procesamiento en memoria.

## 3. Criterios de Aceptación
- `_persist_or_update_execution` no silencia excepciones con retorno `None`; efectúa rollback, registra en `ERROR` y eleva `PersistenceError`.
- `AgentOutput.metadata` contiene el bloque tipado `"persistence"` con el esquema `PersistenceMetadata`.
- Se registran logs con nivel `ERROR` ante cualquier fallo de persistencia en `trigger_execution`, `execute_graph_pipeline` y resolución HITL.
- La ejecución en memoria permanece tolerante a fallos, devolviendo el resultado del agente con la degradación tipada claramente identificable.
- Suite de pruebas completa pasando al 100% (338 tests).
