### Resumen de Implementación — ISSUE-F07-T03

Se ha completado la implementación de los endpoints REST de resolución HITL (`POST /executions/{thread_id}/approve` y `POST /executions/{thread_id}/reject`, junto con sus variantes canónicas `POST /executions/approve` y `POST /executions/reject`) en `jg_agente`, permitiendo al plano de control (`jg_dashboard`) autorizar o denegar operaciones pausadas en el nodo `human_approval` mediante el comando nativo `Command(resume=...)` de LangGraph.

#### 1. Componentes Desarrollados y Modificados
- **`app/models/io.py` & `app/models/__init__.py`:**
  - Creación y exportación de `HITLResolutionRequest`: modelo Pydantic con campos `thread_id`, `approver`, `notes` y `metadata`.
- **`app/nodes/human_approval.py` & `app/nodes/conclude.py`:**
  - Ajuste en `human_approval_node` para desactivar inmediatamente `human_intervention_required = False` y `requires_approval = False` en cuanto la decisión humana (aprobación o rechazo) es recibida vía resume.
  - Ajuste en `conclude_node` para detectar rechazos explícitos y estados de cancelación, sintetizando `AgentOutput` con `status=cancelled` y mensaje explicativo del motivo del rechazo.
- **`app/api/executions.py`:**
  - Implementación de `_resolve_hitl_execution`: valida que el hilo exista en el checkpointer (404 si no existe), que no esté finalizado previamente (409 Conflict si no tiene nodos pendientes), y que se encuentre en espera de aprobación (`human_approval` en `next_nodes`).
  - Emisión de `Command(resume={"approved": ..., "approver": ..., "notes": ..., "action": ...})` para reanudar el grafo sin alterar la semántica de LangGraph.
  - Actualización atómica en la base de datos (`core_executions`), liberando flags de espera (`requires_approval=False`, `pending_approval_id=None`) y actualizando estados finales (`completed` o `cancelled`).
  - Publicación de 4 endpoints REST:
    - `POST /executions/{thread_id}/approve`
    - `POST /executions/{thread_id}/reject`
    - `POST /executions/approve` (con `thread_id` en payload, validando 422 si falta)
    - `POST /executions/reject` (con `thread_id` en payload, validando 422 si falta)
- **`tests/test_api_executions_hitl.py`:**
  - Suite de 6 tests de integración HTTP validando:
    1. Error 404 ante `thread_id` inexistente en el checkpointer.
    2. Error 409 Conflict ante intento de aprobación en hilo ya completado.
    3. Flujo completo de aprobación (`/trigger` -> `waiting_approval` -> `/approve` -> 200 `completed` con ejecución real de la herramienta crítica autorizada y `requires_approval=False`).
    4. Flujo completo de rechazo (`/trigger` -> `waiting_approval` -> `/reject` -> 200 `cancelled` sin ejecutar la herramienta crítica).
    5. Soporte de endpoints con `thread_id` en el cuerpo JSON (`/approve` y `/reject`).
    6. Validación Pydantic 422 Unprocessable Entity cuando falta `thread_id` en llamadas body.

#### 2. Validación y Métricas de Calidad
- `./scripts/check.sh`: **100% verde**.
  - **Ruff:** Linter y formato conformes en los 64 archivos del proyecto.
  - **MyPy:** Modo estricto sin errores en los 64 archivos.
  - **Pytest:** 213 pruebas unitarias e integradas pasando en 0.94 segundos.

#### 3. Cumplimiento de Criterios de Aceptación
- [x] **Reanudación en /approve:** Reanuda el grafo en el paso de ejecución (`execute`), concluyendo exitosamente.
- [x] **Cancelación en /reject:** Cancela el plan de acción, concluye sin invocar la herramienta de riesgo y devuelve `status=cancelled`.
- [x] **Comando nativo Command(resume=...):** Interacción directa con el checkpointer de LangGraph sin bloqueos.
- [x] **Persistencia y auditoría:** Estados sincronizados en PostgreSQL (`core_executions`).

/close
