# Checkpointing y Persistencia de LangGraph

> **Estado del Documento:** ESPECIFICACIÓN TÉCNICA VIVA  
> **Versión:** 2.3.0  
> **Módulo:** `app.core.checkpointer`  

---

## 1. Propósito del Checkpointing

El motor de ejecución de `jg_agente` utiliza **LangGraph** para orquestar los pasos de razonamiento, decisión y acción. El *Checkpointer* es el componente responsable de congelar el estado completo del grafo (`AgentState`) en cada transición de nodo, permitiendo:
1. **Pausado y Reanudación (HITL):** Detener el grafo antes de ejecutar operaciones de alto riesgo (`interrupt_before=["execute"]`) a la espera de autorización humana.
2. **Tolerancia a Fallos:** Reanudar la ejecución en cualquier worker o tras reinicio del servicio a partir de `thread_id`.
3. **Auditoría Forense y Time-Travel:** Inspección histórica de estados pasados del grafo.

---

## 2. Integración con PostgreSQL y Vistas Canónicas `core_`

LangGraph `PostgresSaver` utiliza por defecto nombres fijos (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`). Para garantizar la regla de oro de la plataforma (**todo objeto accesible por el Core debe usar prefijo `core_`**), la inicialización del checkpointer (`app.core.checkpointer.ensure_core_checkpoint_views`) genera vistas SQL actualizables automáticas:

```sql
CREATE OR REPLACE VIEW core_checkpoints AS SELECT * FROM checkpoints;
CREATE OR REPLACE VIEW core_checkpoint_blobs AS SELECT * FROM checkpoint_blobs;
CREATE OR REPLACE VIEW core_checkpoint_writes AS SELECT * FROM checkpoint_writes;
```

En PostgreSQL 9.3+, estas vistas sobre una sola tabla son automáticamente actualizables (`is_updatable = 'YES'`), permitiendo lecturas y escrituras directas.

---

## 3. Arquitectura del Conector

- **Pool de Conexiones:** Basado en `psycopg_pool.ConnectionPool` configurado con:
  - `autocommit=True`: Evita bloqueos en transacciones pendientes.
  - `row_factory=dict_row`: Retorna registros como diccionarios requeridos por el driver de LangGraph.
  - `open=True`: Inicializa el pool de hilos de trabajo de forma limpia y compatible con Python 3.14.
- **Serialización Segura (`JsonPlusSerializer`):**
  - Se define la lista blanca `STATE_ALLOWED_CLASSES` para impedir deserializaciones no autorizadas de código arbitrario.
  - Incluye todos los contratos Core (`AgentInput`, `AgentOutput`, `UserContext`, `PolicyDecision`, `SecurityEvaluationResult`, `AuditRecord`, `ToolResult`, etc.).

---

## 4. Factory Central y Fallback

`get_checkpointer()` suministra la instancia activa según el entorno:
- `get_postgres_checkpointer()`: Producción y persistencia duradera en PostgreSQL.
- `get_memory_checkpointer()`: `MemorySaver` en memoria para suites de pruebas efímeras.

---

## 5. Aislamiento Multi-Agente en Checkpoints (GLOBAL-002 / ISSUE-AGENT-003)

Para evitar colisiones de `thread_id` o contaminación cruzada de estados entre diferentes perfiles de agentes concurrentes:
- Cada perfil de agente (`jg_agente_conversacional` y `jg_agente_devops`) se conecta a una base de datos PostgreSQL física independiente (`DATABASE_URL`).
- Las tablas nativas de LangGraph (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) y las vistas `core_checkpoints*` residen en esquemas completamente aislados por base de datos, garantizando que un hilo conversacional no pueda interferir ni leer los checkpoints o estados de un hilo DevOps.

