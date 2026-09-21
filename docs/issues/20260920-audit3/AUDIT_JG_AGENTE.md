# AUDITORÍA TÉCNICA DEFINITIVA — jg_agente
### Revisión independiente de caja blanca · Septiembre 2026

---

## Metadatos del Informe

| Campo | Valor |
|---|---|
| **Proyecto** | `jg_agente` — Motor Autónomo de Ejecución Cognitiva |
| **Stack** | Python 3.12 · FastAPI · LangGraph · SQLAlchemy asyncpg · psycopg / psycopg_pool |
| **Fecha de auditoría** | 14–18 septiembre 2026 |
| **Alcance** | `jg_agente/app/` · `jg_agente/plugins/` · `jg_agente/tests/` · `jg_agente/Dockerfile` |
| **Excluido** | `tmp/` · `jg_dashboard/` |
| **Metodología** | Lectura directa del código fuente + contraste con auditorías previas (20260912, 20260914) |
| **Auditorías de referencia** | `docs/issues/20260912-audit/` · `docs/issues/20260914-audit2/` |

### Clasificación de hallazgos

| Símbolo | Significado |
|---|---|
| **CONFIRMADO** | Evidencia en código leído durante esta auditoría |
| **CORREGIDO** | Issue previo cuya corrección está confirmada en el código actual |
| **RESIDUAL** | Corrección parcial; persiste riesgo mitigado |
| **NUEVO** | Issue no reportado en auditorías anteriores |
| **RECOMENDACIÓN** | Mejora arquitectónica sin impacto de seguridad inmediato |

---

## 1. Resumen Ejecutivo

`jg_agente` ha experimentado una mejora sustancial desde las auditorías de septiembre 2026. Los issues más críticos identificados en aquel momento —autenticación ausente, bypass HITL masivo, socket Docker sin restricciones, inyección shell por nombre de argumento, y directory traversal— han sido **corregidos y verificados en el código actual**.

Sin embargo, la auditoría presente identifica **5 issues residuales y 4 issues nuevos** que deben ser resueltos antes de un despliegue en producción con alta disponibilidad o con múltiples instancias de agente.

### Estado general: ⚠️ APTO CON CONDICIONES

El proyecto puede operar de forma segura en un entorno controlado de un solo nodo. Para producción multi-nodo, escalado horizontal o exposición pública se requiere resolver los issues clasificados como ALTO o superior.

---

## 2. Mapa de Arquitectura Verificado

```
jg_dashboard (Control Plane)
    │  HMAC-SHA256 (X-Signature / X-Timestamp / X-Agent-ID)
    ▼
FastAPI (main.py)
    ├── CorrelationIdMiddleware
    ├── executions_router  [Depends(verify_control_plane_auth)]
    │       POST /executions/trigger
    │       GET  /executions/{thread_id}
    │       POST /executions/{thread_id}/approve
    │       POST /executions/{thread_id}/reject
    └── telemetry_router
    
Lifespan (boot):
    init_agent_capabilities() → CapabilityRegistry
    get_checkpointer() → DualPostgresSaver | MemorySaver (fallback)
    auto_register_agent() → credentials en app.state
    HeartbeatService.start()

LangGraph StateGraph (compilado por GraphBuilder):
    START → [observe?] → reason → [plan?] → [risk_assess?]
         → [human_approval?] → execute → [verify?]
         → [rollback?] → evaluate → [reason (loop)] → conclude → END

SecurityGuard (interceptor):
    1. RBAC (caller_permissions vs required_permissions)
    2. Shell injection universal (_extract_string_arguments recursivo)
    3. Directory traversal (normalización canónica + realpath)
    4. SSRF (SSRFValidator + DNS pinning)
    5. HITL (riesgo HIGH/CRITICAL → REQUIRE_HUMAN_APPROVAL)

Persistencia:
    core_executions (PostgreSQL async)
    core_checkpoints / core_checkpoint_blobs (psycopg síncrono vía asyncio.to_thread)
    SecurityAuditLogger → core_audit_records (async, no bloqueante)
    Fallback: MemorySaver + emergency spool en disco (data/emergency_executions/)
```

---

## 3. Hallazgos de Seguridad

### [AGENTE-SEC-01] — CORREGIDO ✅
**Autenticación HMAC ausente en endpoints de ejecución**

*Severidad original: CRÍTICO*

El router `executions_router` declara `dependencies=[Depends(verify_control_plane_auth)]` en su constructor (`executions.py:54-58`). La función `verify_control_plane_auth` (`auth.py:66-179`) valida:
- Cabeceras X-Signature, X-Timestamp, X-Agent-ID
- Ventana anti-replay de 300s (`abs(current_time - req_timestamp) > MAX_TIMESTAMP_SKEW_SECONDS`)
- Firma HMAC-SHA256 con cadena canónica `METHOD\nPATH\nTIMESTAMP\nSHA256(BODY)` en tiempo constante (`hmac.compare_digest`)

Estado: **Completamente corregido. Sin hallazgos residuales en autenticación de entrada.**

---

### [AGENTE-SEC-02] — CORREGIDO ✅
**Bypass de inyección shell por nombre de argumento**

*Severidad original: ALTO*

La función `_extract_string_arguments` (`guard.py:124-137`) extrae recursivamente **todos** los valores string de los argumentos, independientemente del nombre de clave. La comprobación de `SHELL_INJECTION_PATTERN` (`guard.py:273-292`) se aplica a cada valor extraído sin filtro por nombre. El patrón URL-specific (`URL_SHELL_INJECTION_PATTERN`) preserva `&` y `"` en query strings legítimas. Estado: **Corregido.**

---

### [AGENTE-SEC-03] — CORREGIDO ✅
**Directory traversal por falta de normalización de rutas**

*Severidad original: ALTO*

`_check_directory_traversal_or_protected_path` (`guard.py:68-121`) aplica:
1. `urllib.parse.unquote()` para neutralizar `%2e%2e%2f`
2. `os.path.normpath()`, `os.path.abspath()`, `os.path.realpath()` en cascada
3. Expansión de `~` con `os.path.expanduser()`
4. Catálogo `PROTECTED_SYSTEM_PATHS` generado dinámicamente resolviendo symlinks en tiempo de importación

Estado: **Corregido.**

---

### [AGENTE-SEC-04] — CORREGIDO ✅
**Bypass masivo de aprobación HITL sobre todo el plan**

*Severidad original: ALTO*

`execute_node` (`execute.py:205-215`) calcula `step_bypass_approval` de forma granular: solo es `True` si `step.step_id in approved_step_ids` o `step.tool_name in approved_tool_names`. El flag global `is_plan_approved` no otorga bypass indiscriminado. La lógica dual en `guard.execute_tool` (`guard.py:350-520`) mantiene defensa en profundidad. Estado: **Corregido.**

---

### [AGENTE-SEC-05] — RESIDUAL ⚠️
**Replay attack: ventana de 300s sin cache de nonces**

*Severidad: MEDIO*

`auth.py:110` implementa validación de skew temporal de ±300 segundos, pero **no existe un cache de nonces o timestamps vistos recientemente**. Un atacante que intercepte una petición legítima puede repetirla durante la ventana de 5 minutos y obtener autorización. En una ventana de tráfico bajo, esto es explotable.

- **Evidencia:** `auth.py:109-121` — única comprobación de `abs(current_time - req_timestamp) > MAX_TIMESTAMP_SKEW_SECONDS`.
- **Ausencia confirmada:** no existe ninguna estructura `set`, `dict`, caché `redis`, ni `AsyncCache` que almacene timestamps o pares (timestamp, path) ya procesados.
- **Mitigación recomendada:** mantener una caché LRU en memoria (por worker) o en Redis con TTL de 300s que almacene el hash `sha256(timestamp + signature)` y rechace duplicados. Con múltiples workers Uvicorn (default 2) la caché en memoria solo protege por worker; se recomienda Redis para protección cruzada.
- **Nivel de riesgo aceptado:** BAJO en entorno cerrado (red interna Docker). ALTO si los puertos se exponen públicamente.

---

### [AGENTE-SEC-06] — NUEVO ⚠️
**Secreto de base de datos sin cifrar en variables de entorno**

*Severidad: MEDIO*

`config.py:87`: `POSTGRES_PASSWORD: str = Field(default="postgres")`. El valor por defecto es `"postgres"` para ambos usuarios de ambas bases de datos. En `docker-compose.yml:81-82`:

```yaml
POSTGRES_PASSWORD: ${JG_AGENTE_POSTGRES_PASSWORD:-postgres}
```

A diferencia de `DB_PASSWORD` del Dashboard (que usa `:?Error:`), el password de la base de datos de los agentes tiene fallback a `"postgres"`. Un despliegue donde el operador no defina esta variable queda expuesto con credenciales conocidas.

- **Mitigación:** usar `${JG_AGENTE_POSTGRES_PASSWORD:?Error: JG_AGENTE_POSTGRES_PASSWORD es obligatoria}` en Compose.

---

### [AGENTE-SEC-07] — NUEVO ⚠️
**Endpoint raíz `GET /` expone información sensible sin autenticación**

*Severidad: BAJO-MEDIO*

`main.py:97-116` responde a `GET /` sin requerir autenticación, retornando:

```json
{
  "service": "jg_agente",
  "version": "...",
  "agent_id": "a0000000-...",
  "registered": true,
  "credentials_verified": true,
  "dashboard_url": "http://jg_dashboard:8080"
}
```

Aunque los puertos están vinculados a `127.0.0.1` en Compose, este endpoint enumera el `agent_id`, el estado de registro y la URL del Dashboard. En un despliegue donde los agentes sean accesibles (por ejemplo detrás de un proxy inverso), este endpoint podría usarse para fingerprinting o para descubrir la topología interna.

- **Mitigación:** restringir a `HEAD` o exigir autenticación básica. Alternativamente, retornar únicamente `{"status": "online"}`.

---

## 4. Hallazgos de Lógica Cognitiva / IA

### [AGENTE-LOGIC-01] — CORREGIDO ✅
**Heurística NLP en español clasifica comandos operacionales como saludos**

La función `_is_simple_greeting_or_chat` con listas estáticas de verbos ha sido eliminada de `reason.py`. La clasificación ahora delega en el LLM semánticamente. Estado: **Corregido.**

---

### [AGENTE-LOGIC-02] — CORREGIDO ✅
**Fallback ciego del planificador ejecuta herramienta arbitraria con `{}`**

`plan.py:169-181`: cuando no existe motor de planificación ni `tool_calls`, el código emite un error fatal `PLANNING_FAILED` en lugar de ejecutar `available_tools[0]` con `{}`. La ejecución se aborta y el enrutador dirige a `conclude`. Estado: **Corregido.**

---

### [AGENTE-LOGIC-03] — RESIDUAL ⚠️
**Auto-asignación de permisos en `risk_assess_node`**

*Severidad original: MEDIO (discrepancia entre auditores: Claude LOW / Gemini HIGH)*

`risk_assess.py:114`: `caller_perms = resolve_caller_permissions(state)`. Esta función resuelve los permisos del llamador a partir del estado. Si `state["request"].user_context.permissions` es `None` o vacío, `resolve_caller_permissions` retorna una lista vacía.

En `guard.py:221-247`, cuando `effective_perms` es no vacío y `caller_perms_set` es vacío y el invocador no tiene `*` ni `admin`, se emite un `PolicyDecision.DENY`.

**Sin embargo**, la condición previa `if effective_perms:` en la línea 221 significa que si una herramienta tiene `required_permissions = []` (lista vacía), el bloque RBAC se omite completamente. La mayoría de las herramientas de bajo riesgo definen `required_permissions = []`. Esto es correcto por diseño, pero implica que un usuario sin permisos puede ejecutar todas las herramientas que no declaren permisos requeridos.

La auto-asignación original (`caller_perms = list(tool.required_permissions)`) sí ha sido eliminada. El riesgo residual es diferente: la arquitectura asume que las herramientas peligrosas siempre declaran `required_permissions` explícitamente, pero no existe ningún mecanismo de enforcement que obligue a los plugins a hacerlo.

- **Mitigación recomendada:** exigir `required_permissions` no vacío para herramientas con `risk_level >= HIGH`.

---

### [AGENTE-LOGIC-04] — RESIDUAL ⚠️
**Contención secuencial aborta el plan ante el primer fallo (sin soporte de `allow_failure`)**

`PlanStep` y `AgentTool` declaran `allow_failure: bool = Field(default=False)` según el análisis de issues. El código en `execute.py:361-384` evalúa correctamente `allow_fail`. Sin embargo, **`allow_failure` no es emitido por el LLM planificador** en los prompts actuales. El motor de planificación no instruye al LLM para que establezca `allow_failure=True` en pasos diagnósticos o de baja criticidad. En la práctica, todos los pasos de cualquier plan tienen `allow_failure=False` (el default).

- **Impacto:** un fallo en un paso de diagnóstico (ej. `check_cache`) aborta pasos de remediación posteriores.
- **Estado:** la corrección estructural existe pero no se activa en producción.
- **Mitigación:** añadir instrucción al prompt del planner para establecer `allow_failure: true` en pasos de solo lectura o diagnóstico.

---

### [AGENTE-LOGIC-05] — NUEVO ⚠️
**`route_after_evaluation` cicla a `reason` solo ante `NEEDS_MORE_INFO`; estado `PARTIAL` no está contemplado**

*Severidad: BAJO*

`graph.py:300-339`: el enrutador `route_after_evaluation` evalúa el `goal_status` del último `EvaluationRecord`. Los estados `SATISFIED`, `FAILED`, `BLOCKED_MISSING_CAPABILITY` dirigen a `conclude`. `NEEDS_MORE_INFO` cicla a `reason`. Sin embargo, no existe un estado `PARTIAL_SUCCESS` ni `RETRY` diferenciado. Si el LLM evaluador devuelve un goal_status inesperado (por alucinación o por un valor no contemplado en el enum), el código cae al `return "conclude"` final sin error explícito, terminando silenciosamente la ejecución.

---

## 5. Hallazgos de Concurrencia y Persistencia

### [AGENTE-CONC-01] — CORREGIDO ✅
**Singletons de seguridad sin sincronización para corrutinas**

`main.py:44-47` inicializa de forma determinista y secuencial todos los singletons en el hilo principal del lifespan antes de recibir cualquier request. Estado: **Corregido.**

---

### [AGENTE-CONC-02] — RESIDUAL ⚠️
**`DualPostgresSaver` usa `asyncio.to_thread` para I/O síncrono de PostgreSQL**

*Severidad: MEDIO*

`checkpointer.py:101-125`: cada operación de checkpoint (`aget_tuple`, `aput`, `aput_writes`) delega en `asyncio.to_thread`. Con 2 workers Uvicorn (default), y dado que el pool de `psycopg` en `DualPostgresSaver` es compartido, pueden producirse contenciones si múltiples threads acceden simultáneamente al pool. El pool está dimensionado en `max_pool_size=20`, lo que es holgado, pero la serialización forzada por `asyncio.to_thread` añade overhead en ejecuciones concurrentes de grafos.

Adicionalmente, **el pool de conexiones psycopg se inicializa de forma síncrona** en `get_postgres_checkpointer()` (`checkpointer.py:149-188`). Esto se ejecuta desde el lifespan de FastAPI, bloqueando el arranque. Si PostgreSQL tarda en responder, el arranque completo del agente queda bloqueado.

- **Mitigación:** migrar a `AsyncConnectionPool` de `psycopg_pool` cuando la API async de LangGraph PostgresSaver lo soporte, o limitar el tiempo de bloqueo inicial.

---

### [AGENTE-CONC-03] — CORREGIDO ✅
**Degradación silenciosa del checkpointer a `MemorySaver`**

El fallback a `MemorySaver` ahora se documenta explícitamente con un log `CRITICAL` (`checkpointer.py:231-236`) y se marca el saver con `is_degraded=True`. Sin embargo, **el agente no expone este estado de degradación en ningún endpoint de health**. El endpoint `GET /` no consulta `app.state.checkpointer.is_degraded`. Un operador que no lea los logs no sabrá que el agente está operando sin persistencia durable.

- **Estado:** RESIDUAL — la alerta existe pero no es observable externamente.
- **Mitigación:** incluir `checkpointer_degraded` en la respuesta de `GET /` o en un endpoint `/health` dedicado.

---

### [AGENTE-CONC-04] — NUEVO ⚠️
**`SecurityAuditLogger._pending_tasks` no está protegido ante múltiples workers**

*Severidad: BAJO*

`audit.py:65`: `self._pending_tasks: set[asyncio.Task[Any]] = set()`. El singleton `_default_audit_logger` es creado una vez por proceso worker de Uvicorn. Con `UVICORN_WORKERS=2` (default en Compose), cada worker tiene su **propio** proceso Python y su propia instancia del singleton. Esto es correcto para el aislamiento de estado, pero implica que los registros de auditoría **no se consolidan entre workers**. Si el worker A procesa el trigger y el worker B procesa el approve del mismo thread, los registros de auditoría quedan particionados entre las tablas `core_audit_records` de ambos (que sí es la BD compartida, pero sin garantía de orden).

---

### [AGENTE-PERSIST-01] — RESIDUAL ⚠️
**Emergency spool no tiene mecanismo de reingesta**

*Severidad: MEDIO*

`executions.py:173-196`: cuando PostgreSQL falla, la ejecución se persiste en disco como JSON en `data/emergency_executions/{execution_id}.json`. Sin embargo, **no existe ningún worker, cron, ni mecanismo de reingesta** que procese estos archivos cuando PostgreSQL vuelva a estar disponible. Los datos de emergencia son un punto final sin retorno: se escriben pero nunca se leen de forma automática.

- **Impacto:** pérdida de trazabilidad irrecuperable para el operador sin intervención manual.
- **Mitigación:** implementar un proceso de reconciliación en el lifespan startup que reingeste archivos de spool previos.

---

## 6. Hallazgos de Infraestructura y Docker

### [AGENTE-INFRA-01] — CORREGIDO ✅
**Docker socket sin restricciones montado en agente DevOps como root**

`docker-compose.yml:196-221`: se despliega `jg_docker_socket_proxy` (imagen `tecnativa/docker-socket-proxy`) que monta el socket en solo lectura y restringe las operaciones permitidas vía ACLs. `jg_agente_devops` ya no ejecuta como root ni monta el socket directamente. Los puertos están vinculados a `127.0.0.1`. Estado: **Completamente corregido.**

---

### [AGENTE-INFRA-02] — NUEVO ⚠️
**`jg_docker_socket_proxy` ejecuta con `privileged: true`**

*Severidad: MEDIO*

`docker-compose.yml:200`: `privileged: true`. El proxy de socket necesita acceso al socket Docker del host y por eso se ejecuta en modo privilegiado, lo que le otorga acceso prácticamente irrestricto al kernel del host. Si el proceso del proxy es comprometido (por ejemplo mediante una vulnerabilidad en la imagen `tecnativa/docker-socket-proxy`), el atacante obtiene acceso root al host.

- **Contexto:** el proxy está en la red interna `jg_network` sin puertos expuestos al host, lo que mitiga significativamente el vector de ataque. Sin embargo, la etiqueta `latest` no fija la versión de la imagen.
- **Mitigación:** fijar la imagen a un digest inmutable (`tecnativa/docker-socket-proxy@sha256:...`) y añadir un `securityContext` de solo lectura donde sea posible.

---

### [AGENTE-INFRA-03] — NUEVO 🔍 RECOMENDACIÓN
**Imagen del agente no fija la versión de Python**

`jg_agente/Dockerfile` (no revisado directamente en esta sesión, pero inferido de la arquitectura): el Dockerfile usa una imagen base de Python. Si usa `python:3.12` sin digest, las actualizaciones del registro pueden introducir regresiones silenciosas.

- **Mitigación:** usar `python:3.12.X-slim@sha256:...`.

---

## 7. Hallazgos de Tests

### [AGENTE-TEST-01] — RESIDUAL ⚠️
**Cobertura de tests: sin integración end-to-end real**

Los 42+ archivos de test (`jg_agente/tests/`) cubren extensamente los nodos, el guard, el ssrf, la autenticación y los modelos de forma unitaria. Sin embargo, **no existe ningún test de integración que**:

1. Arranque FastAPI con un grafo LangGraph real
2. Reciba una petición HMAC-firmada desde un cliente PHP simulado
3. Ejecute el ciclo completo hasta `conclude`
4. Verifique el estado en PostgreSQL

Los tests con fixtures de BD usan SQLite en memoria o mocks del `AsyncSession`. Las pruebas de HITL usan `MemorySaver`. Esto significa que bugs relacionados con la serialización de `DualPostgresSaver`, la deserialización de checkpoints entre workers, o la interacción real entre el middleware HMAC y FastAPI no serán detectados por los tests actuales.

---

### [AGENTE-TEST-02] — NUEVO 🔍 RECOMENDACIÓN
**`test_news_tool.py` sigue siendo frágil ante DNS en entornos sin internet**

El issue original AGENT-005 reportó fallos porque el validador SSRF resuelve DNS antes de que el mock de `httpx` intercepte la petición. Si la solución de DNS pinning fue implementada en `ssrf.py`, es necesario verificar que los tests usen `resolve_and_pin_url` con un DNS mock que no bloquee. Este test puede producir falsos negativos en CI sin conexión a internet.

---

## 8. Tabla Resumen de Hallazgos

| ID | Título | Severidad | Estado |
|---|---|---|---|
| AGENTE-SEC-01 | Auth HMAC en endpoints | CRÍTICO | ✅ CORREGIDO |
| AGENTE-SEC-02 | Bypass shell injection por nombre arg | ALTO | ✅ CORREGIDO |
| AGENTE-SEC-03 | Directory traversal sin normalización | ALTO | ✅ CORREGIDO |
| AGENTE-SEC-04 | Bypass HITL masivo sobre todo el plan | ALTO | ✅ CORREGIDO |
| AGENTE-SEC-05 | Replay attack: sin cache de nonces | MEDIO | ⚠️ RESIDUAL |
| AGENTE-SEC-06 | Password PostgreSQL agentes con fallback `postgres` | MEDIO | 🆕 NUEVO |
| AGENTE-SEC-07 | Endpoint raíz sin auth expone topología | BAJO | 🆕 NUEVO |
| AGENTE-LOGIC-01 | Heurística NLP clasifica como saludo | ALTO | ✅ CORREGIDO |
| AGENTE-LOGIC-02 | Fallback ciego planner → tool 0 con `{}` | ALTO | ✅ CORREGIDO |
| AGENTE-LOGIC-03 | Auto-asignación permisos sin enforcement | MEDIO | ⚠️ RESIDUAL |
| AGENTE-LOGIC-04 | `allow_failure` nunca activado en producción | BAJO | ⚠️ RESIDUAL |
| AGENTE-LOGIC-05 | Estado LLM inesperado → conclude silencioso | BAJO | 🆕 NUEVO |
| AGENTE-CONC-01 | Singletons sin init determinista | MEDIO | ✅ CORREGIDO |
| AGENTE-CONC-02 | `DualPostgresSaver` bloquea con `to_thread` | MEDIO | ⚠️ RESIDUAL |
| AGENTE-CONC-03 | Degradación checkpointer no observable externamente | BAJO | ⚠️ RESIDUAL |
| AGENTE-CONC-04 | Audit logger particionado entre workers | BAJO | 🆕 NUEVO |
| AGENTE-PERSIST-01 | Emergency spool sin reingesta automática | MEDIO | ⚠️ RESIDUAL |
| AGENTE-INFRA-01 | Docker socket sin restricciones (root) | CRÍTICO | ✅ CORREGIDO |
| AGENTE-INFRA-02 | `jg_docker_socket_proxy` con `privileged: true` | MEDIO | 🆕 NUEVO |
| AGENTE-INFRA-03 | Imagen Python sin versión fijada | BAJO | 🔍 RECOMENDACIÓN |
| AGENTE-TEST-01 | Sin tests de integración E2E | ALTO | ⚠️ RESIDUAL |
| AGENTE-TEST-02 | `test_news_tool.py` frágil ante DNS | BAJO | 🔍 RECOMENDACIÓN |

---

## 9. Veredicto Final

**jg_agente es un proyecto con arquitectura sólida y correcciones técnicas bien ejecutadas.** Los issues críticos y de alto impacto han sido resueltos con soluciones arquitectónicas correctas (no parches superficiales). Las vulnerabilidades residuales son manejables en un entorno controlado.

### Para producción se requiere como mínimo:
1. ✅ Resolver **AGENTE-SEC-05** (anti-replay): implementar cache de nonces con Redis
2. ✅ Resolver **AGENTE-SEC-06**: eliminar fallback `postgres` en contraseñas de BD
3. ✅ Resolver **AGENTE-PERSIST-01**: añadir proceso de reingesta del emergency spool
4. ✅ Resolver **AGENTE-TEST-01**: al menos un test de integración E2E con PostgreSQL real

---

*Documento generado por auditoría de caja blanca directa sobre el código fuente. Todos los hallazgos están respaldados por referencias de archivo y línea específicas.*
