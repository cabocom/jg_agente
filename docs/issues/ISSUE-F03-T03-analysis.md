# Análisis Técnico: ISSUE-F03-T03 — Implementación de SecurityAuditLogger

> **Issue ID:** ISSUE-F03-T03  
> **Fase:** FASE 03 (Persistencia y Checkpointing)  
> **Prioridad:** High  
> **Complejidad:** S  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

Para dar soporte a la trazabilidad forense, observabilidad y cumplimiento normativo (compliance) en `jg_agente`, cada operación ejecutada por el agente debe generar trazas inmutables en la base de datos relacional.
El servicio `SecurityAuditLogger` debe:
1. Registrar de forma estructurada en la tabla `core_audit_records` cada:
   - **Estímulo:** Recepción de inputs normalizados (`AgentInput`).
   - **Decisión de riesgo:** Evaluaciones y veredictos del subsistema de políticas (`SecurityGuard`).
   - **Ejecución de tool:** Invocación de herramientas (`AgentTool`), duración, éxito/fallo y contexto de compensación.
   - **Cambio de estado:** Transición del ciclo de vida (`AgentExecutionStatus`).
   - **Aprobación humana:** Decisiones HITL (`ApprovalRecord`).
2. **Garantizar no-bloqueo en ejecución asíncrona:** La persistencia hacia PostgreSQL se efectúa en segundo plano (`asyncio.create_task`) utilizando un pool transaccional async, sin bloquear la latencia del agente ni detener el ciclo de inferencia/ejecución.
3. **Resiliencia de auditoría:** Si la clave foránea `execution_id` no existe aún en `core_executions` (o en caso de ejecuciones efímeras), el registro persiste desacoplado preservando la referencia en los detalles sin descartar la traza ni lanzar excepciones no controladas.

---

## 2. Reutilización y Adaptación (Código Origen)

- Se tomó la interfaz y lógica en memoria de `Devops60k/app/tools/security/audit.py`.
- Se enriqueció de forma sustancial incorporando persistencia asíncrona en PostgreSQL (`core_audit_records`), modelo ORM `CoreAuditRecord` y métodos semánticos tipados:
  - `record(evaluation: SecurityEvaluationResult, execution_id: str | None = None)`
  - `record_stimulus(input_data: AgentInput)`
  - `record_tool_execution(tool_name, tool_args, result, risk_level, execution_id, thread_id)`
  - `record_state_transition(old_status, new_status, execution_id, thread_id, reason)`
  - `record_approval(approval, execution_id, thread_id)`
  - `record_event(...)`
- Se incorporaron al Core los modelos `PolicyDecision` y `SecurityEvaluationResult` en `app.models.state` y `app.core.checkpointer`.

---

## 3. Decisiones de Diseño

1. **Persistencia No Bloqueante con Tareas de Fondo (`asyncio.create_task`):**
   - El registrador programa tareas asíncronas de inserción en BD y mantiene una referencia activa en `_pending_tasks` para evitar recolección prematura por el recolector de basura (garbage collector).
   - Se provee el método `flush()` para sincronizar y esperar a que todas las tareas en vuelo concluyan limpiamente.
2. **Estructuración Canónica de Detalles:**
   - Todo evento persiste obligatoriamente con `timestamp`, `actor`, `risk_level` y `result` estructurados, cumpliendo estrictamente los criterios de aceptación.
3. **Manejo de Errores y Aislamiento:**
   - Si la base de datos experimenta un fallo transitorio o error de conectividad, `SecurityAuditLogger` captura la excepción, la registra en el log del sistema y preserva la traza en su buffer en memoria, impidiendo que una falla de auditoría provoque la caída del pipeline de razonamiento del agente.
4. **Patrón Singleton y Soporte para Inyección de Dependencias:**
   - La factoría `get_security_audit_logger()` entrega una instancia global, permitiendo a la vez inyectar factorías de sesiones personalizadas (`session_factory`) durante pruebas unitarias o de integración.

---

## 4. Criterios de Aceptación Verificados

- [x] Persistencia de eventos estructurados en `core_audit_records`.
- [x] Inclusión obligatoria de `timestamp`, `actor`, `risk_level` y `result` en cada registro.
- [x] Persistencia asíncrona no bloqueante verificada con `asyncio.create_task` y `flush()`.
- [x] Tolerancia a ejecuciones no vinculadas (`unlinked_execution_id`) ante restricciones FK.
- [x] 61 tests pasando en suite completa con 100% de cobertura en linter y tipado estricto.
