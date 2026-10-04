# 04. Persistencia, Estado y Checkpointing (`jg_agente`)

[← Volver al README](../README.md) | [← 03. Seguridad](03_security_sandboxing.md) | [05. Plugins →](05_plugin_lifecycle.md)

---

## 1. Arquitectura de Almacenamiento Durable

`jg_agente` utiliza PostgreSQL como motor de persistencia principal para dos propósitos bien diferenciados:
1. **Estado de la Máquina de Estados LangGraph:** Checkpoints, estados de nodos, trazas cognitivas y datos de interrupción HITL.
2. **Registro Relacional de Auditoría y Ejecución:** Tablas estructuradas para reporting, observabilidad y trazabilidad operativa.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        PostgreSQL de jg_agente                         │
│                                                                        │
│   Tablas de Checkpoints (LangGraph)      Tablas de Dominio Core        │
│   ┌──────────────────────────────┐       ┌──────────────────────────┐  │
│   │ checkpoints                  │       │ core_executions          │  │
│   │ checkpoint_blobs             │       │ (ejecuciones, prompt,    │  │
│   │ checkpoint_writes            │       │  status, payload, I/O)   │  │
│   └──────────────▲───────────────┘       └──────────────────────────┘  │
│                  │                                                     │
│                  │ Vistas canónicas                                    │
│   ┌──────────────┴───────────────┐       ┌──────────────────────────┐  │
│   │ core_checkpoints             │       │ core_audit_records       │  │
│   │ core_checkpoint_blobs        │       │ (eventos inmutables      │  │
│   │ core_checkpoint_writes       │       │  de seguridad y tools)   │  │
│   └──────────────────────────────┘       └──────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Checkpointing con `DualPostgresSaver`

`DualPostgresSaver` (`app/core/checkpointer.py`) extiende `langgraph.checkpoint.postgres.PostgresSaver` para resolver la impedancia entre el driver síncrono subyacente y el bucle de eventos asíncrono de FastAPI:

### 2.1 Arquitectura Híbrida Sync-Async (`asyncio.to_thread`)
`PostgresSaver` nativo de LangGraph depende de conexiones bloqueantes de `psycopg` (v3). Si un framework asíncrono como FastAPI ejecuta operaciones de checkpoint directamente en el bucle principal, se producen bloqueos de I/O que degradan la concurrencia.

`DualPostgresSaver` resuelve esto instanciando un `ConnectionPool` de `psycopg` configurado con:
```python
ConnectionPool(
    conninfo=db_url,
    min_size=settings.DB_POOL_MIN_SIZE,
    max_size=settings.DB_POOL_MAX_SIZE,
    kwargs={"autocommit": True, "row_factory": dict_row}
)
```
Y sobreescribe todos los métodos asíncronos (`aget_tuple`, `aput`, `aput_writes`, `alist`) envolviendo las llamadas síncronas canónicas (`get_tuple`, `put`, `put_writes`, `list`) mediante:
```python
await asyncio.to_thread(self.get_tuple, config)
```
De este modo, las operaciones intensivas de I/O a PostgreSQL se descargan al pool de hilos de Python, manteniendo el Event Loop de FastAPI completamente desahogado para atender peticiones concurrentes y streaming HTTP.

### 2.2 Vistas Canónicas `core_checkpoints*`
Para cumplir con la convención de nomenclatura estricta del Core y evitar colisiones si la base de datos se comparte, durante el `setup()` del checkpointer se crean o actualizan automáticamente vistas alias:
```sql
CREATE OR REPLACE VIEW core_checkpoints AS SELECT * FROM checkpoints;
CREATE OR REPLACE VIEW core_checkpoint_blobs AS SELECT * FROM checkpoint_blobs;
CREATE OR REPLACE VIEW core_checkpoint_writes AS SELECT * FROM checkpoint_writes;
```

---

## 3. Serialización de Estado y Sanitización Profunda

### 3.1 Lista Blanca Estricta de Clases Msgpack (`STATE_ALLOWED_CLASSES`)
LangGraph serializa el estado del grafo cognitivo utilizando `JsonPlusSerializer` / Msgpack. Para neutralizar vectores de inyección de objetos arbitrarios durante la deserialización (Object Injection / Remote Code Execution), `DualPostgresSaver` impone una lista blanca explícita (`STATE_ALLOWED_CLASSES` en `app/core/checkpointer.py`).

Únicamente las siguientes clases y namespaces están autorizados para persistirse en los checkpoints:
- **Modelos I/O del Core:** `AgentInput`, `AgentOutput`, `UserContext`, `ExecutionStatus`.
- **Enumeraciones y Estados Cognitivos:** `AgentExecutionStatus`, `ApprovalStatus`, `StepStatus`, `VerificationStatus`, `GoalStatus`, `PolicyDecision`.
- **Estructuras de Planificación y Registro:** `ExecutionPlan`, `PlanStep`, `ApprovalRecord`, `StepExecutionRecord`, `AuditRecord`, `CognitiveStepRecord`, `EvaluationRecord`, `ObservationRecord`.
- **Contratos Canónicos de `jg_agente_sdk`:** Todos los modelos bajo `jg_sdk.contracts.*` (`ToolCall`, `ToolResult`, `SecurityContext`, `PluginMetadata`, `CapabilityDefinition`, etc.).

> [!WARNING]
> **Aislamiento en Plugins:** Si un plugin personalizado intenta guardar en el estado del grafo instancias de clases de negocio propias no registradas en `STATE_ALLOWED_CLASSES`, la serialización de LangGraph lanzará una excepción y la transacción se abortará. Los plugins deben devolver datos primitivos (`dict`, `list`, `str`, `int`) o modelos estándar del SDK dentro de `ToolResult.data`.

### 3.2 Sanitización Recursiva de Corrutinas (`_async_sanitize_for_storage`)
En entornos asíncronos complejos, si una herramienta o nodo inyecta accidentalmente un objeto `coroutine` o `Future` no esperado dentro del diccionario de estado, Msgpack fallará catastróficamente al intentar serializarlo.

Para evitar esto, `app/core/checkpointer.py` implementa la función `_async_sanitize_for_storage(obj, max_depth=8)`:
- **Recorrido en Profundidad Limitada:** Inspecciona diccionarios, listas, tuplas, conjuntos y atributos de objetos hasta una profundidad máxima de 8 niveles.
- **Detección de Awaitables:** Si detecta un objeto de tipo `asyncio.Future`, `Task` o `inspect.iscoroutine`:
  - Si el objeto ya ha finalizado, extrae su resultado resuelto.
  - Si el objeto sigue pendiente o no resuelto, lo neutraliza y sustituye por un marcador seguro inmutable: `"[Unresolved awaitable: <coroutine_name>]"`.
- **Protección contra Referencias Circulares:** Mantiene un registro de identidades de objetos visitados para prevenir bucles infinitos durante la sanitización.

---

## 4. Tablas Relacionales del Core

Además de las tablas binarias de checkpoints de LangGraph, `jg_agente` mantiene tablas relacionales legibles para auditoría y observabilidad:

### 4.1 `core_executions`
Gestiona el ciclo de vida completo de cada invocación (`app/db/models.py`):
- `execution_id` (String 64, PK): Identificador unívoco generado mediante UUID v4.
- `thread_id` (String 128, Index): Identificador de la sesión o conversación multilínea.
- `status` (String 32): Estado de ciclo de vida (`in_progress`, `completed`, `waiting_approval`, `failed`, `cancelled`).
- `prompt` (Text): Entrada original enviada por el usuario/sistema emisor.
- `response` (Text): Respuesta final sintetizada tras la conclusión del grafo.
- `parameters`, `data`, `user_context`, `metadata`: Campos JSON estructurados para payload contextual y variables de sesión.
- `execution_time_ms` (Float): Latencia total de extremo a extremo observada en milisegundos.
- `requires_approval` (Boolean) y `pending_approval_id` (String 128): Registro de retención por Human-In-The-Loop.
- `created_at` y `completed_at` (DateTime UTC con zona horaria).

### 4.2 `core_audit_records`
Registro inmutable para cumplimiento normativo y trazabilidad operativa:
- `id` (BigInteger, PK autoincremental).
- `execution_id` (String 64, FK opcional con `core_executions`).
- `event_type` (String 64): Tipo de evento auditado (`security_decision`, `tool_executed`, `hitl_requested`, `rollback_executed`, etc.).
- `actor` (String 64): Componente emisor (`core`, `security_guard`, `human_operator`, `llm_synthesizer`).
- `details` (JSON): Metadatos, argumentos sanitizados y decisiones tomadas.
- `timestamp` (DateTime UTC con zona horaria).

---

## 5. Resiliencia, Degradación y Spooling de Emergencia

En caso de fallo de red, saturación o indisponibilidad transitoria del servidor PostgreSQL:

```text
┌────────────────────────────────────────────────────────┐
│             Intento de Checkpoint / Estado             │
└──────────────────────────┬─────────────────────────────┘
                           │
                 ¿Conexión a Postgres OK?
                 ├── SÍ ──► Escribe en checkpoints / core_executions
                 │
                 └── NO
                      │
                      ▼
         Reintentos con Backoff Exponencial
         (Hasta PERSISTENCE_MAX_RETRIES = 3)
                      │
                      ├── ¿Recuperado? ──► OK
                      │
                      └── Agotados
                           │
                           ▼
                  Conmutación a Memoria
                  (MemorySaver, is_degraded = True)
                           │
                           ▼
               ¿Error crítico al finalizar?
                           │
                           ▼
          Spooling de Emergencia en Disco Local
          (data/emergency_executions/{execution_id}.json)
          PersistenceStatus.SPOOLED
```

### 5.1 Reintentos con Backoff Exponencial
Toda operación de base de datos se ejecuta bajo un esquema de reintentos configurable (`PERSISTENCE_MAX_RETRIES`, por defecto 3) con pausas crecientes para absorber reinicios de contenedor o cortes temporales de red.

### 5.2 Modo Degradado en Memoria
Si PostgreSQL no responde tras agotar los reintentos, el checkpointer conmuta a `MemorySaver` en memoria y marca el estado de degradación (`is_degraded = True`). El agente continúa respondiendo peticiones en caliente, registrando advertencias de alta prioridad en el log estructurado.

### 5.3 Spooling de Emergencia en Disco (`EMERGENCY_PERSISTENCE_DIR`)
Si la persistencia de un resultado final o estado crítico de HITL falla irrecuperablemente en PostgreSQL:
1. El runtime intercepta la excepción en la capa de finalización.
2. Serializa el estado completo, resultados de herramientas y metadatos de auditoría en formato JSON.
3. Lo escribe de forma atómica en el directorio configurado por `EMERGENCY_PERSISTENCE_DIR` (por defecto: `data/emergency_executions/{execution_id}.json`).
4. Retorna el resultado con el estado `PersistenceStatus.SPOOLED` en lugar de fallar silenciosamente o perder los datos procesados.
5. Se emite una alerta crítica de observabilidad para que los operadores o tareas de mantenimiento puedan reinyectar los ficheros spooled a PostgreSQL una vez restaurado el servicio.

---

## 5. Navegación

- [← Anterior: 03. Seguridad, Aislamiento de Red y Sandboxing](03_security_sandboxing.md)
- [Índice General](../README.md)
- [Siguiente: 05. Ciclo de Vida y Ecosistema de Plugins →](05_plugin_lifecycle.md)
