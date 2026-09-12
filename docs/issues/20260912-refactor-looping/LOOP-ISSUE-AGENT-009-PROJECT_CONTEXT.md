# Contexto de Proyecto: [LOOP-ISSUE-AGENT-009] Nodo de evaluación semántica (evaluate_node) y Capability-Awareness

## 1. Identificación y Estado
- **Issue ID:** LOOP-ISSUE-AGENT-009
- **GitLab Item:** [#50](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/50) (jg_agente)
- **Epic:** `EPIC-LOOPING-01` (Razonamiento Iterativo y Bucles de Pensamiento Proactivos)
- **Fase:** Fase 2 - Nodo de Evaluación Semántica y Capability-Awareness
- **Prioridad:** High / Core Cognitive Architecture
- **Complejidad Estimada:** M
- **Estado:** En Planificación

## 2. Alineación Arquitectónica
En el diseño lineal previo, el agente no disponía de una etapa de reflexión tras ejecutar herramientas; simplemente concluía volcando los resultados técnicos directos.

El propósito de `LOOP-ISSUE-AGENT-009` es dotar al agente de una capa de **reflexión y auditoría semántica (`evaluate_node`)**, utilizando el mismo modelo LLM activo en el agente (`get_chat_model()` con Groq `openai/gpt-oss-120b`).

### Principios Clave:
1. **Evaluación Semántica de Objetivos:**
   El LLM compara la solicitud original del usuario con la evidencia recopilada en `execution_records`, `messages` (ToolMessages) y `environment_snapshot`. Determina si el objetivo ha sido resuelto o si requiere pasos complementarios.
2. **Capability-Awareness (Honestidad y Proactividad):**
   Si el agente descubre una anomalía (ejemplo: un contenedor reiniciándose constantemente) y para llegar a la causa raíz requiere una herramienta ausente en su catálogo (como `docker:logs`), no entra en bucle infinito ni arroja un error técnico opaco. Emite el estado `GoalStatus.BLOCKED_MISSING_CAPABILITY` y formula una explicación proactiva para el operador humano, indicando qué capacidad falta y sugiriendo la acción recomendada.
3. **Trazabilidad en Consola Operativa:**
   Genera un `CognitiveStepRecord` para cada iteración, visible en la consola web de `jg_dashboard` como un paso cognitivo más en la línea de tiempo.

## 3. Criterios de Aceptación
- Creación de `app/nodes/evaluate.py` con función asíncrona `evaluate_node(state, registry, llm=None)`.
- El nodo evalúa la evidencia contra el catálogo activo de herramientas y genera un `EvaluationRecord` estructurado.
- Ante herramientas ausentes, clasifica como `BLOCKED_MISSING_CAPABILITY` y reporta la lista de herramientas faltantes.
- Emite un `CognitiveStepRecord` con metadatos completos y actualiza `is_resolved`.
- Parsing defensivo ante respuestas no-JSON o fallos del modelo.
- Suite de pruebas unitarias exhaustiva en `tests/test_node_evaluate.py` (meta cumplida, necesidad de más información, capability ausente y fallback defensivo).
- `bash scripts/check.sh` pasa al 100% (Ruff, MyPy y Pytest).
