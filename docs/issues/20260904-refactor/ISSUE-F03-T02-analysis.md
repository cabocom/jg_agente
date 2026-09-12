# Análisis Técnico: ISSUE-F03-T02 — Integración de Checkpointer LangGraph sobre PostgreSQL (PostgresSaver)

> **Issue ID:** ISSUE-F03-T02  
> **Fase:** FASE 03 (Persistencia y Checkpointing)  
> **Prioridad:** Critical  
> **Complejidad:** M  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

En flujos de agentes cognitivos y orquestaciones con interacción humana en el bucle (Human-in-the-Loop, HITL), es indispensable contar con persistencia durable del estado entre transiciones de grafos.
LangGraph utiliza el concepto de *Checkpointer* para congelar el estado completo de la máquina de estados en cada superpaso (nodo), permitiendo:
1. Pausar la ejecución antes de nodos sensibles (como solicitudes de aprobación para herramientas de riesgo HIGH/CRITICAL).
2. Reanudar la ejecución en cualquier momento (incluso en otros workers o tras reinicios del servicio) a partir del identificador de hilo (`thread_id`).
3. Soportar viajes en el tiempo e inspección forense del estado.

**Requisito arquitectónico fundamental:**
Todo objeto de base de datos accesible o gestionado por el Core debe cumplir la convención de prefijos `core_`. Para el checkpointer de LangGraph, las consultas y persistencia deben operar de manera canónica sobre `core_checkpoints`.

---

## 2. Reutilización y Adaptación (Código Origen)

- Se tomaron los patrones de serialización segura y conexión por pool de `Devops60k/src/devops60k/core/checkpointer.py` y `jg-ai-gateway`.
- Se integró `langgraph-checkpoint-postgres` y `psycopg[binary,pool]` en `pyproject.toml`.
- Se adaptó la serialización `JsonPlusSerializer` para incorporar de forma explícita todos los modelos Core de `app.models.io`, `app.models.state` y `app.models.tools`.
- Se diseñó el mecanismo de vistas actualizables `core_checkpoints`, `core_checkpoint_blobs` y `core_checkpoint_writes` sobre las tablas generadas por `saver.setup()`, resolviendo elegantemente el nombre rígido interno de LangGraph sin comprometer la pureza de esquemas del Core.

---

## 3. Decisiones de Diseño

1. **Vistas Actualizables (`core_checkpoints`):**
   - LangGraph `PostgresSaver` utiliza internamente tablas fijas (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`).
   - Para garantizar que la arquitectura del sistema y cualquier componente externo consuma y audite bajo la convención `core_*`, se crearon vistas SQL actualizables automáticas en la inicialización:
     - `core_checkpoints` -> `checkpoints`
     - `core_checkpoint_blobs` -> `checkpoint_blobs`
     - `core_checkpoint_writes` -> `checkpoint_writes`
   - En PostgreSQL 9.3+, las vistas simples son automáticamente actualizables (`is_updatable = 'YES'`), posibilitando lecturas y escrituras directas.

2. **Gestión de Conexiones mediante `psycopg_pool.ConnectionPool`:**
   - Configurado con `row_factory=dict_row`, `autocommit=True` y `open=True`, garantizando transacciones atómicas y compatibilidad estricta de tipos con MyPy.

3. **Serialización Segura y Homologada (`JsonPlusSerializer`):**
   - Para prevenir deserialización arbitraria o no segura, se restringe la lista de módulos permitidos (`STATE_ALLOWED_CLASSES`) incluyendo todas las entidades Pydantic del Core (`AgentInput`, `AgentOutput`, `AuditRecord`, `ToolResult`, etc.), tanto bajo sus rutas de submódulo (`app.models.state`, `app.models.io`, `app.models.tools`) como a nivel de paquete (`app.models`).

4. **Factory Unificada con Fallback:**
   - `get_checkpointer()` resuelve dinámicamente entre `PostgresSaver` y `MemorySaver` en función de la configuración del entorno, asegurando que los tests efímeros o entornos sin BD puedan ejecutarse fluidamente.

---

## 4. Criterios de Aceptación Verificados

- [x] `PostgresSaver` configurado y conectado a PostgreSQL (`ConnectionPool`).
- [x] Vistas `core_checkpoints`, `core_checkpoint_blobs` y `core_checkpoint_writes` creadas y verificadas.
- [x] Flujo de prueba StateGraph de LangGraph con interrupción HITL (`interrupt_before=["execute"]`) ejecutado.
- [x] Persistencia física de checkpoints confirmada en `core_checkpoints`.
- [x] Reanudación exitosa desde el hilo guardado (`invoke(None, config=thread_config)`) preservando y acumulando mensajes y trazas de auditoría.
