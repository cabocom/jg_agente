# Análisis de Causa Raíz: [AGENTE-STATE-03] Doble Sesión de Base de Datos Concurrente por Request Saturation Pool

## Diagnóstico Técnico
1. **Retención Prolongada de Conexiones por Inyección de Dependencias:**
   Los endpoints `trigger_execution` y las rutas HITL (`approve_execution_by_thread_id`, `reject_execution_by_thread_id`, `approve_execution`, `reject_execution`) declaraban en su firma el parámetro `db: AsyncSession = Depends(get_async_session)`.
   FastAPI reserva la conexión del pool antes de invocar la función de ruta y solo la libera (haciendo commit/close) al completar la respuesta.
   Al ser operaciones síncronas o de larga duración vinculadas a llamadas de red (LLMs, tools externas), el pool quedaba exhausto con tráfico concurrente mínimo.

2. **Desacoplamiento Interno Inconsistente:**
   Dentro del pipeline de ejecución, la función `_persist_with_retry` (y previamente `_persist_or_update_execution`) no utilizaba la sesión inyectada por FastAPI, sino que invocaba explícitamente `async with async_session_factory() as db:` para garantizar transacciones atómicas aisladas.
   En consecuencia, la sesión inyectada en la firma del endpoint era completamente superflua, no realizaba operaciones útiles y únicamente servía para bloquear conexiones en el pool.

3. **Impacto en Escalabilidad y Estabilidad:**
   Bajo cargas de trabajo reales o ráfagas concurrentes, el agente experimentaba excepciones de timeout de conexión (`TimeoutError: QueuePool limit reached`), provocando que peticiones legítimas fallasen con errores 500 o degradación.

## Estrategia de Solución
1. **Eliminación Total de `get_async_session` en Rutas de Grafos:**
   Eliminar el parámetro `db: AsyncSession` de:
   - `trigger_execution`
   - `approve_execution_by_thread_id`
   - `reject_execution_by_thread_id`
   - `approve_execution`
   - `reject_execution`
   - `_resolve_hitl_execution`
2. **Uso de Sesiones de Ámbito Corto (Scoped Sessions):**
   Confiar exclusivamente en `_persist_with_retry` con `async_session_factory()`, adquiriendo la conexión solo durante los milisegundos necesarios para insertar o actualizar el registro en `core_executions` y devolviéndola inmediatamente al pool.
3. **Preservación Legítima en Lecturas Puntuales:**
   Mantener `get_async_session` únicamente en endpoints de lectura rápida como `GET /executions/{thread_id}` o endpoints de telemetría que concluyen en <5ms sin ejecutar grafos.
