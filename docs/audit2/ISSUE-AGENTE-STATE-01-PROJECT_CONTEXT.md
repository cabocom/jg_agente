# Contexto del Proyecto: [AGENTE-STATE-01] Persistencia Best-Effort Oculta Pérdida de Ejecuciones en Base de Datos

## Descripción del Entorno
- **Componente:** `jg_agente` (Execution Plane)
- **Capa Afectada:** API REST (`app/api/executions.py`) y Persistencia Relacional (`app/db/`)
- **Base de Datos:** PostgreSQL (`core_executions`)

## Contexto Operativo
En el flujo de ejecución de `jg_agente`, cada orden recibida a través de `POST /executions/trigger` o resuelta en `POST /executions/{thread_id}/approve` debe registrarse transaccionalmente en la tabla `core_executions`. Dicha tabla constituye la fuente de verdad primaria para el historial de tareas, trazabilidad de auditoría, auditoría forense y consumo desde el Dashboard (`jg_dashboard`).

Anteriormente, las operaciones de persistencia hacia PostgreSQL se ejecutaban bajo una política *best-effort*. Si PostgreSQL experimentaba un fallo temporal (desconexión, bloqueo transaccional, saturación del connection pool o reinicio), el agente capturaba la excepción, registraba una advertencia en los logs y devolvía al cliente una respuesta **HTTP 200 OK** con metadatos `persistence.status = "degraded"` y `persisted = False`.

Como consecuencia directa:
1. El Dashboard y los clientes externos asumían erróneamente que la ejecución había culminado de forma satisfactoria sin percibir ningún error.
2. La ejecución se perdía silenciosamente de `core_executions`, provocando que consultas posteriores por `thread_id` o listados históricos no encontrasen registro alguno.
3. Se generaban discrepancias críticas entre el checkpointer de LangGraph y la base de datos relacional.
