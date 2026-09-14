# Contexto del Proyecto: [AGENTE-STATE-03] Doble Sesión de Base de Datos Concurrente por Request Saturation Pool

## Descripción del Entorno
- **Componente:** `jg_agente` (Execution Plane)
- **Capa Afectada:** API REST de Ejecución y HITL (`app/api/executions.py`)
- **Gestor de Base de Datos:** SQLAlchemy Async / PostgreSQL (`QueuePool`)
- **Severidad:** 🟡 MEDIO

## Contexto Operativo
`jg_agente` procesa ejecuciones cognitivas a través de grafos de LangGraph. Los puntos de entrada principales son:
1. `POST /executions/trigger`: Dispara la ejecución síncrona o asíncrona del pipeline.
2. `POST /executions/{thread_id}/approve` y `POST /executions/approve`: Reanudan la ejecución tras autorización humana (HITL).
3. `POST /executions/{thread_id}/reject` y `POST /executions/reject`: Cancelan el plan y concluyen el grafo tras rechazo de un operador.

Durante la ejecución del grafo (`execute_graph_pipeline` o `_resolve_hitl_execution`), el agente puede demorar de varios segundos a minutos interactuando con modelos LLM, ejecutando herramientas del sistema, evaluando riesgos de seguridad y resolviendo dependencias.

## Problema Detectado
FastAPI gestiona dependencias como `db: AsyncSession = Depends(get_async_session)` abriendo una sesión y reservando una conexión del connection pool al inicio de la petición HTTP, manteniéndola ocupada hasta que el manejador de la ruta retorna la respuesta.

Al inyectar `db: AsyncSession` en los endpoints de ejecución y resolución:
1. La conexión de base de datos permanecía retenida de forma ociosa durante todo el ciclo de vida del grafo cognitivo.
2. Simultáneamente, el pipeline interno invoca `_persist_with_retry`, el cual abre sus propias sesiones independientes mediante `async_session_factory()`.
3. Esto generaba una **doble sesión concurrente** por petición.
4. Con un tamaño por defecto de 5 conexiones en el connection pool (`QueuePool`), tan solo 5 peticiones simultáneas consumían las 5 conexiones retenidas por FastAPI, provocando saturación inmediata (`QueuePool limit of size 5 overflow 10 reached`) y bloqueando cualquier otra operación en el agente.
