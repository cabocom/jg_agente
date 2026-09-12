# Contexto de Proyecto: [LOOP-ISSUE-AGENT-008] Extensión de AgentState, contratos de iteración y preparación de mensajes

## 1. Identificación y Estado
- **Issue ID:** LOOP-ISSUE-AGENT-008
- **GitLab Item:** [#49](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/49) (jg_agente)
- **Epic:** `EPIC-LOOPING-01` (Razonamiento Iterativo y Bucles de Pensamiento Proactivos)
- **Fase:** Fase 1 - Contratos, Estado y Preparación de Mensajes
- **Prioridad:** High / Core Architecture
- **Complejidad Estimada:** S
- **Estado:** En Planificación

## 2. Alineación Arquitectónica
En el diseño original del motor cognitivo de `jg_agente`, el grafo se ejecutaba como una secuencia lineal sin retorno (`observe -> reason -> plan -> execute -> verify -> conclude`).

Para dotar al agente de capacidad de razonamiento iterativo, proactividad y evaluación semántica sin romper la compatibilidad con LangGraph ni los checkpoints persistentes de PostgreSQL (`DualPostgresSaver` / `core_checkpoints`), se requiere:
1. **Contador y Límites de Iteración:**
   - Incorporar `iteration: int` (iniciando en 1) y `max_iterations: int` (por defecto 3) en `AgentState`.
2. **Contrato Estructurado de Evaluación (`EvaluationRecord` y `GoalStatus`):**
   - Definir los estados de resolución del objetivo: `satisfied`, `needs_more_info`, `blocked_missing_capability` y `failed`.
   - Permitir registrar explicaciones semánticas, detección de herramientas ausentes y sugerencias de siguiente acción cognitiva.
3. **Autorización en Serializador del Checkpointer (`STATE_ALLOWED_CLASSES`):**
   - Registrar `GoalStatus` y `EvaluationRecord` en `app/core/checkpointer.py` para evitar que el serializador `JsonPlusSerializer` rechace el checkpoint al persistir en base de datos.
4. **Alimentación Completa de la Memoria en `execute_node`:**
   - En `app/nodes/execute.py`, los pasos originados a partir de un plan previo no emitían `ToolMessage` a `state["messages"]`. Al activar ciclos iterativos, el siguiente salto de `reason` necesita ver obligatoriamente las salidas de las herramientas ejecutadas para poder decidir qué hacer a continuación.

## 3. Criterios de Aceptación
- `AgentState` define `iteration`, `max_iterations` y `evaluation_records` con reducer acumulador `append_reducer`.
- `app/core/checkpointer.py` incluye `GoalStatus` y `EvaluationRecord` en `STATE_ALLOWED_CLASSES`.
- `execute_node` inyecta `ToolMessage` en `state["messages"]` tanto para llamadas directas como para pasos de plan.
- Pruebas unitarias en `tests/test_loop_state_contracts.py` validan la creación, serialización y actualización del estado.
- La suite completa de tests de `jg_agente` (41+ tests) pasa al 100%.
