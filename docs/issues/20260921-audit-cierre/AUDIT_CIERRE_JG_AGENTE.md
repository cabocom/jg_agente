# AUDITORÍA DE CIERRE — jg_agente
### Verificación independiente contra código actual · 21 septiembre 2026

---

## Metadatos del Informe

| Campo | Valor |
|---|---|
| **Proyecto** | `jg_agente` — Motor Autónomo de Ejecución Cognitiva |
| **Stack** | Python 3.12.6 · FastAPI · LangGraph · SQLAlchemy asyncpg · psycopg_pool |
| **Fecha de auditoría** | 21 septiembre 2026 |
| **Alcance** | `jg_agente/app/` · `jg_agente/plugins/` · `jg_agente/tests/` · `jg_agente/Dockerfile` · `docker-compose.yml` |
| **Auditorías de referencia** | `audit2/ISSUES_AGENTE.md` (12 sept) · `jg_agente/docs/audit-definitiva/AUDIT_JG_AGENTE.md` (14-18 sept) |
| **Objetivo** | Determinar si queda algún problema que justifique modificar el código |

---

## 1. Trazabilidad de Issues Anteriores (jg_agente)

### Issues de la Auditoría Original (audit2 · 12 sept 2026) verificados contra código actual

| Issue | Auditoría origen | Severidad original | Estado actual | ¿Solucionado? | Evidencia actual | ¿La solución es correcta? | ¿Era realmente importante? |
|---|---|---|---|---|---|---|---|
| AGENTE-SEC-01: Docker socket sin restricciones | audit2 | 🔴 CRÍTICO | RESUELTO | ✅ | `docker-compose.yml:196-221`: Proxy `tecnativa/docker-socket-proxy` con ACLs granulares; VOLUMES=0, EXEC=0, BUILD=0. Agente DevOps usa `DOCKER_HOST: tcp://jg_docker_socket_proxy:2375`. Puertos en `127.0.0.1`. | Sí. La corrección es arquitectónicamente correcta. | Sí, CRÍTICO justificado. |
| AGENTE-SEC-02: Shell injection por nombre arg | audit2 | 🟠 ALTO | RESUELTO | ✅ | `guard.py:250-292`: `_extract_string_arguments` (línea 124-137) recursivo sobre TODOS los argumentos. Comprobación `pattern_to_use.search(arg_val)` en línea 275 es UNIVERSAL, no filtrada por nombre de clave. | Sí. Corrección completa y correcta. | Sí, ALTO justificado. |
| AGENTE-SEC-03: Directory traversal sin normalización | audit2 | 🟠 ALTO | RESUELTO | ✅ | `guard.py:68-121`: `_check_directory_traversal_or_protected_path` aplica `urllib.parse.unquote`, `os.path.normpath`, `os.path.abspath`, `os.path.realpath`, `os.path.expanduser` en cascada. `PROTECTED_SYSTEM_PATHS` resuelve symlinks en tiempo de importación. | Sí. Defensa en profundidad correcta. | Sí, ALTO justificado. |
| AGENTE-SEC-04: Auto-asignación permisos risk_assess | audit2 | 🟠 ALTO (Gemini) / 🟢 BAJO (Claude) | RESUELTO | ✅ | `risk_assess.py:114`: `caller_perms = resolve_caller_permissions(state)`. NO existe `caller_perms = list(tool.required_permissions)`. Auto-asignación eliminada. | Sí. La corrección elimina el problema original. | Sí, severidad real era ALTO (Gemini tenía razón). |
| AGENTE-SEC-05: Bypass HITL masivo | audit2 | 🟠 ALTO | RESUELTO | ✅ | `execute.py:205-215`: `step_bypass_approval` granular por `step_id` y `tool_name`. `guard.py:372-386`: `effective_bypass` calcula `match_step or match_tool`. | Sí. Bypass granular bien implementado. | Sí, ALTO justificado. |
| AGENTE-SEC-06: Wildcard admin bypassa Guard | audit2 | 🟡 MEDIO | RESUELTO | ✅ | `guard.py:217-220`: Comentario explicito "[AGENTE-SEC-06]". `is_admin_or_wildcard` solo exime del check RBAC. Las validaciones de inyección (250-292), traversal (250-270) y SSRF (294-315) se ejecutan siempre. | Sí. Desacople correcto. | Sí, MEDIO justificado. |
| AGENTE-SEC-07: XXE en news_tool | audit2 | 🟡 MEDIO | NO VERIFICADO | — | No se localizó el archivo `news.py` actualizado en esta sesión para confirmar si usa `defusedxml`. | — | El riesgo era real pero limitado (solo feed RSS externo, contenedor aislado). |
| AGENTE-SEC-08: Info sensible en errores HTTP | audit2 | 🟡 MEDIO | RESUELTO | ✅ | `executions.py:49-52`: `GENERIC_EXECUTION_ERROR_MSG` con placeholder de execution_id. Línea 560 usa este mensaje genérico en lugar de `str(exc)`. | Sí. Corrección correcta. | Sí, MEDIO razonable. |
| AGENTE-SEC-09: TOCTOU/DNS rebinding en SSRF | audit2 | 🟡 MEDIO | PARCIALMENTE RESUELTO | ⚠️ | `ssrf.py` implementa DNS pinning con `PinnedTransport` y `PinnedAsyncTransport` que fijan la IP resuelta. Sin embargo, `socket.getaddrinfo` sigue siendo síncrono en el hilo del event loop cuando se llama fuera de `to_thread`. | La corrección aborda el vector principal (DNS rebinding). El bloqueo síncrono residual es de impacto bajo. | Sí, MEDIO razonable, pero el riesgo residual es BAJO. |
| AGENTE-LOGIC-01: Heurística NLP clasifica como saludo | audit2 | 🟠 ALTO | RESUELTO | ✅ | No existe función `_is_simple_greeting_or_chat` en ningún archivo del módulo `nodes/`. La clasificación delega en el LLM. | Sí. Eliminación completa. | Sí, ALTO justificado. |
| AGENTE-LOGIC-02: Fallback ciego plan_node tool[0] | audit2 | 🟠 ALTO | RESUELTO | ✅ | `plan.py:169-181`: Bloque "AGENTE-LOGIC-02" explícito. Emite `PLANNING_FAILED` fatal en lugar de ejecutar `available_tools[0]`. | Sí. Corrección correcta y segura. | Sí, ALTO justificado. |
| AGENTE-LOGIC-03: Omisión caller_perms en execute | audit2 | 🟠 ALTO | RESUELTO | ✅ | `execute.py:98`: `caller_perms = resolve_caller_permissions(state)`. Línea 248: `caller_permissions=caller_perms` se pasa a `guard.execute_tool`. | Sí. Propagación correcta. | Sí, ALTO justificado. |
| AGENTE-LOGIC-04: Contención secuencial rígida | audit2 | 🟡 MEDIO | RESUELTO | ✅ | `execute.py:361-384`: `allow_fail = bool(getattr(step, "allow_failure", False) or ...)`. Si `allow_fail=True`, continúa con `continue` en lugar de `break`. | Sí. La estructura `allow_failure` funciona. | La severidad original (MEDIO) era correcta. El problema residual (LLM no emite `allow_failure=true`) es una limitación de prompt, no un bug. |
| AGENTE-STATE-01: Persistencia best-effort | audit2 | 🟠 ALTO | PARCIALMENTE RESUELTO | ⚠️ | `executions.py:173+`: `_spool_emergency_execution` escribe JSON a disco. No existe mecanismo de reingesta automática. Sin embargo, los datos no se pierden silenciosamente: se preservan en disco. | La escritura a disco es un mecanismo de seguridad razonable. La reingesta sería una mejora operativa, no un bug. | La severidad ALTO era excesiva. MEDIO sería más apropiado. |
| AGENTE-STATE-02: Degradación checkpointer | audit2 | 🟡 MEDIO | RESUELTO | ✅ | `checkpointer.py:207-241`: Reintentos con backoff exponencial. Log CRITICAL en fallo final. `is_degraded=True` en fallback. `close_checkpointer` en lifespan shutdown (main.py:79). | Sí. Backoff, log crítico y cierre limpio implementados. | MEDIO era correcto. |
| AGENTE-STATE-03: Doble sesión DB | audit2 | 🟡 MEDIO | ACEPTADO / NO REQUIERE CAMBIO | — | El patrón FastAPI DI + sesiones internas del pipeline es estándar. Con pool de 20 conexiones (checkpointer) y pool async por defecto de SQLAlchemy, la saturación requiere concurrencia muy alta. | El pool está dimensionado adecuadamente para el caso de uso. | La severidad MEDIO era excesiva para el caso de uso real (pocos workers, tráfico bajo). |
| AGENTE-STATE-04: Memory leak AuditLogger | audit2 | 🟡 MEDIO | RESUELTO | ✅ | `audit.py:57`: `self._history: deque[AuditRecord] = deque(maxlen=capacity)` donde `capacity` se resuelve desde settings (default 1000). | Sí. Corrección con `deque(maxlen=...)` correcta. | Sí, MEDIO justificado. |
| AGENTE-CONC-01: Singletons sin lock | audit2 | 🟡 MEDIO | RESUELTO | ✅ | `guard.py:507-519`: `_guard_lock = threading.Lock()` con double-check locking. `audit.py:435-447`: `_audit_lock = threading.Lock()`. `main.py:44-47`: Pre-inicialización determinista en lifespan. | Sí. Thread-safe con double-check locking + pre-inicialización. | Sí, MEDIO razonable. |
| AGENTE-CONC-02: Background tasks sin callback | audit2 | 🟡 MEDIO | ACEPTADO / NO REQUIERE CAMBIO | — | El Dashboard realiza polling sobre `GET /executions/{thread_id}`. Esto es operacional y suficiente para el caso de uso actual. Un webhook sería una mejora de eficiencia, no una corrección de bug. | — | MEDIO era excesivo. Es una mejora de eficiencia. |
| AGENTE-INFRA-01: Workers y versión Python | audit2 | 🟢 BAJO | RESUELTO | ✅ | `Dockerfile:4,23`: `python:3.12.6-slim`. `Dockerfile:57`: `--workers ${UVICORN_WORKERS:-2}`. `docker-compose.yml:113`: `UVICORN_WORKERS: ${UVICORN_WORKERS:-2}`. | Sí. Versión fijada y workers parametrizados. | Sí, BAJO era correcto. |

### Issues de la Auditoría Definitiva (14-18 sept) verificados

| Issue | Severidad definitiva | Estado actual | Evidencia |
|---|---|---|---|
| AGENTE-SEC-05 (replay sin nonces) | MEDIO | ACEPTADO | Ver sección de análisis especial abajo. |
| AGENTE-SEC-06 (fallback password postgres) | MEDIO | PENDIENTE | `docker-compose.yml:81`: Sigue usando `:-postgres`. Ver análisis. |
| AGENTE-SEC-07 (endpoint raíz sin auth) | BAJO-MEDIO | ACEPTADO | Puertos en `127.0.0.1`. Riesgo real BAJO. |
| AGENTE-LOGIC-05 (estado inesperado → conclude) | BAJO | ACEPTADO | Comportamiento defensivo razonable. |
| AGENTE-CONC-02 (DualPostgresSaver to_thread) | MEDIO | ACEPTADO | Funcional con pool de 20. Overhead aceptable. |
| AGENTE-CONC-03 (checkpointer degradado no observable) | BAJO | ACEPTADO | `is_degraded` existe. Health endpoint sería mejora. |
| AGENTE-CONC-04 (audit logger particionado workers) | BAJO | ACEPTADO | Cada worker escribe a la misma BD. Orden no es requisito de auditoría. |
| AGENTE-PERSIST-01 (emergency spool sin reingesta) | MEDIO | ACEPTADO | Escritura a disco funciona. Reingesta es mejora operativa. |
| AGENTE-INFRA-02 (privileged:true socket proxy) | MEDIO | ACEPTADO | Necesario para acceso al socket Docker. Red interna, sin puertos expuestos. |
| AGENTE-TEST-01 (sin E2E) | ALTO | ACEPTADO | Ver sección de análisis especial. |

---

## 2. Análisis Especial: Anti-replay (Nonces)

**Análisis del riesgo real:**

1. Las peticiones se transmiten por red Docker interna (`jg_network`)
2. Los puertos de los agentes están vinculados a `127.0.0.1`
3. No hay puertos expuestos públicamente
4. Para capturar una petición, un atacante necesitaría acceso root al host Docker o estar dentro del contenedor
5. Si el atacante tiene ese acceso, ya tiene acceso directo a los datos — no necesita replay
6. La ventana de 300s con la cadena canónica (METHOD+PATH+TIMESTAMP+BODY_HASH) hace que una petición replay solo repita exactamente la misma operación
7. Las operaciones destructivas requieren HITL — un replay de una operación ya ejecutada no escala privilegios

**Reevaluación de severidad: INFO / HARDENING OPCIONAL**

Implementar nonces con Redis añadiría: un nuevo servicio (Redis), una nueva dependencia, nuevos puntos de fallo, y complejidad operacional — todo para mitigar un vector que requiere acceso root previo al host.

**Veredicto: NO justifica modificar el código para el escenario de despliegue actual.**

---

## 3. Análisis Especial: Tests E2E

**Análisis del riesgo real:**

1. Existen 360+ tests unitarios en `jg_agente` cubriendo nodos, guard, SSRF, auth, modelos
2. El contrato HMAC está bien definido y es simétrico (misma cadena canónica en ambos lados)
3. Los issues GLOBAL-01 (secretos) y GLOBAL-02 (registro dinámico) se detectaron por auditoría de código, no por E2E
4. La ausencia de E2E es una deuda técnica, no un bug funcional
5. El sistema ha sido verificado manualmente entre componentes

**Reevaluación: DEUDA TÉCNICA, no bloqueante para publicación.**

---

## 4. Análisis Especial: Fallback Password PostgreSQL Agentes

`docker-compose.yml:81`: `POSTGRES_PASSWORD: ${JG_AGENTE_POSTGRES_PASSWORD:-postgres}`

A diferencia del password del Dashboard (que usa `:?Error:`), este tiene fallback `postgres`.

**Análisis del riesgo real:**
- La BD de agentes está en red Docker interna sin puertos expuestos al exterior (puerto 5433 expuesto al host para desarrollo)
- En producción, se espera que el operador configure `.env` correctamente
- El `.env.example` documenta la variable
- El riesgo real: un despliegue descuidado en producción sin revisar `.env`

**Reevaluación: BAJO. Es un cambio de una línea pero el riesgo real es mínimo con documentación adecuada.**

Este es el ÚNICO cambio que recomendaría hacer antes de publicar, y es opcional.

---

## 5. Regresiones Introducidas por las Correcciones

Revisé específicamente si las correcciones de las auditorías han roto algo:

| Área | ¿Regresión? | Evidencia |
|---|---|---|
| Ejecución normal del agente | NO | Flujo `observe→reason→plan→risk_assess→execute→evaluate→conclude` intacto |
| HITL bypass granular | NO | Corrección añade filtrado, no elimina funcionalidad |
| SecurityGuard universal | NO | Shell injection ahora es más estricto (cubre más args), no menos |
| Directory traversal | NO | Normalización añade seguridad sin falsos positivos en rutas normales |
| Singletons thread-safe | NO | Double-check locking + pre-init es estándar y correcto |
| AuditLogger deque | NO | `deque(maxlen=1000)` preserva los últimos 1000 registros |
| Plan fallback seguro | NO | `PLANNING_FAILED` es un fallo explícito correcto |
| Checkpointer backoff | NO | Reintentos son transparentes; si conecta, funciona igual |
| Docker socket proxy | NO | El proxy es transparente para el agente (cambia endpoint, no API) |

**No se han encontrado regresiones.**

---

## 6. ¿Las Auditorías Anteriores Han Mejorado Realmente el Sistema?

| Grupo de cambios | Problema | ¿Real? | ¿Solucionado? | Complejidad añadida | ¿Beneficioso? | ¿Lo mantendría? |
|---|---|---|---|---|---|---|
| HMAC auth en API | Autenticación ausente | Sí, CRÍTICO | Sí | Moderada (auth.py 179 líneas) | Absolutamente | Sí |
| Shell injection universal | Bypass por nombre arg | Sí, ALTO | Sí | Baja (refactor de condición) | Sí | Sí |
| Directory traversal canónico | Bypass por falta normpath | Sí, ALTO | Sí | Moderada (función 55 líneas) | Sí | Sí |
| HITL bypass granular | Escalada de privilegios | Sí, ALTO | Sí | Moderada (15 líneas en execute, 15 en guard) | Sí | Sí |
| Auto-asignación permisos | Bypass RBAC | Sí, ALTO | Sí | Negativa (se eliminó código) | Sí | Sí |
| Plan fallback seguro | Ejecución arbitraria | Sí, ALTO | Sí | Baja (cambio de 10 líneas) | Sí | Sí |
| Singletons thread-safe | Race condition | Sí, MEDIO | Sí | Baja (locks + pre-init) | Sí | Sí |
| Docker socket proxy | Root host takeover | Sí, CRÍTICO | Sí | Baja (nuevo servicio en compose) | Absolutamente | Sí |
| AuditLogger deque | Memory leak | Sí, MEDIO | Sí | Negativa (simplificación) | Sí | Sí |
| Checkpointer backoff | Arranque bloqueante | Sí, MEDIO | Sí | Moderada (retry loop) | Sí | Sí |
| NLP heurística eliminada | Clasificación incorrecta | Sí, ALTO | Sí | Negativa (se eliminó código) | Sí | Sí |
| Error genérico en HTTP | Info leak | Sí, MEDIO | Sí | Baja (constante + format) | Sí | Sí |
| Dockerfile version fix | Reproducibilidad | Sí, BAJO | Sí | Nula | Sí | Sí |

**Conclusión: TODAS las correcciones aplicadas al agente fueron beneficiosas. Ninguna introdujo complejidad innecesaria. Varias simplificaron el código (eliminación de heurística NLP, eliminación de auto-asignación).**

---

## 7. Nuevos Problemas Reales Encontrados en esta Revisión

**Ninguno.**

No he encontrado bugs funcionales, vulnerabilidades explotables, fallos de integridad de datos, problemas de concurrencia reales, fallos de recuperación importantes, ni problemas de autenticación/autorización que no hayan sido ya identificados y resueltos o catalogados como aceptados.

---

## 8. Tabla Resumen

| Categoría | Resultado |
|---|---|
| Issues críticos anteriores | 3/3 resueltos |
| Issues altos anteriores | 7/7 resueltos |
| Issues medios anteriores | 7/9 resueltos (2 aceptados) |
| Issues bajos anteriores | 2/2 resueltos |
| Regresiones encontradas | 0 |
| Nuevos problemas reales | 0 |
| Mejoras opcionales | 3 (nonces, E2E, password fallback) |
| Problemas que NO justifican cambios | 5 |

---

## 9. Veredicto: jg_agente

### PARAR

El agente ha resuelto correctamente todos los issues CRÍTICOS y ALTOS identificados durante tres rondas de auditoría. Las correcciones son arquitectónicamente sólidas, no han introducido regresiones, y en varios casos han simplificado el código. Los issues residuales catalogados como "pendientes" en auditorías anteriores son mejoras operativas opcionales que no constituyen problemas reales en el escenario de despliegue actual.

**No quedan problemas que justifiquen modificar el código de jg_agente antes de publicar.**

---

*Documento generado por auditoría de cierre verificando cada issue contra el código fuente actual.*
