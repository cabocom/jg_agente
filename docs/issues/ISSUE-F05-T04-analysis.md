# Análisis Técnico: ISSUE-F05-T04 — Implementación de nodo base: conclude

> **Issue ID:** `ISSUE-F05-T04`  
> **Fase:** `FASE 05`  
> **Componente:** `jg_agente.nodes.conclude`  
> **Fecha:** 5 de septiembre de 2026  
> **Prioridad:** Critical | **Complejidad:** S  
> **Dependencias:** `ISSUE-F05-T01` (GraphBuilder)

---

## 1. Contexto y Objetivos

El nodo `conclude` es el nodo terminal de convergencia y síntesis en el grafo cognitivo LangGraph de `jg_agente`. Todos los flujos operacionales (resolución directa de `reason`, finalización tras `execute`, comprobación post-ejecución en `verify` o compensaciones en `rollback`) convergen en `conclude`, el cual conecta de forma invariable con el nodo `END` de LangGraph para dar por concluido el hilo de ejecución.

Su responsabilidad es unificar la salida del agente, formatear la respuesta textual final, computar los tiempos de ciclo y construir el contrato normalizado de salida `AgentOutput`.

---

## 2. Requisitos y Criterios de Aceptación

- **Criterio de Aceptación:** `Nodo conclude finaliza el hilo LangGraph, marca status=completed y devuelve AgentOutput válido con tiempos de ejecución.`
- **Evaluación del Desenlace Operacional:** Discriminar con precisión entre ejecuciones exitosas (`is_resolved=True`, `AgentExecutionStatus.RESOLVED`, `ExecutionStatus.COMPLETED`) y ejecuciones fallidas (`is_resolved=False`, `AgentExecutionStatus.FAILED`, `ExecutionStatus.FAILED`) inspeccionando `errors`, `execution_records` y el estado previo.
- **Formateo Determinista de la Respuesta:** Extraer o sintetizar la respuesta textual para el usuario respetando la precedencia de `AIMessage` con contenido, `IntentModel.parameters["response"]`, resumen de herramientas ejecutadas o fallos.
- **Cómputo de Métricas Temporales:** Calcular `execution_time_ms` a partir de `request.created_at` (wall-clock time) o agregando las duraciones individuales `duration_ms` de las herramientas ejecutadas.
- **Persistencia en el Estado:** Almacenar `output: AgentOutput` en `AgentState["output"]` para que el `StateSnapshot` de LangGraph contenga el contrato canónico completo.
- **Auditoría Inmutable:** Emitir registro estructurado `AuditRecord` bajo el evento `execution_concluded` con métricas de tiempo, pasos y desenlace.

---

## 3. Decisiones de Diseño

1. **Jerarquía y Coherencia de Enums de Estado:**
   - En `AgentOutput`: el campo `status` es de tipo `ExecutionStatus` (`COMPLETED` = `"completed"`, `FAILED` = `"failed"`).
   - En `AgentState`: el campo `status` mantiene `AgentExecutionStatus.RESOLVED` / `FAILED`, asegurando retrocompatibilidad total con los checkpoints y routers de LangGraph.
2. **Cálculo Robusto de `execution_time_ms`:**
   - Se toma el máximo entre el tiempo transcurrido desde `request.created_at` y la suma de duraciones de herramientas (`total_tool_ms`), asegurando que nunca se infravalore el tiempo consumido.
3. **Carga de Datos Estructurados (`data`):**
   - Se recopilan las trazas de `execution_records`, `environment_snapshot`, `verification_results` y `rollback_records` en el payload `data` de `AgentOutput`.
