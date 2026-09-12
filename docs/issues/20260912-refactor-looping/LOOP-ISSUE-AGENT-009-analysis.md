# Análisis Técnico: [LOOP-ISSUE-AGENT-009] Nodo de evaluación semántica (evaluate_node) y Capability-Awareness

## 1. Diagnóstico del Estado Previo

### 1.1 Inexistencia de Reflexión Post-Ejecución
Actualmente, el flujo cognitivo pasa de `execute` a `verify` (que solo comprueba fallos booleanos técnicos) y de ahí directo a `conclude`.
No existe ningún punto donde el LLM pueda:
- Analizar si el contenido retornado por una herramienta responde a lo que el humano pidió.
- Detectar anomalías que ameriten una acción exploratoria adicional.
- Identificar que carece de las herramientas necesarias para responder en profundidad.

### 1.2 Riesgo de "Bucle Ciego" o Respuestas Superficiales
Sin un evaluador semántico consciente de sus propias capacidades, cualquier ciclo que intente regresar a `reason`:
- O bien repetiría ciegamente la misma herramienta en un bucle infinito si la respuesta no le convence.
- O bien alucinaría que puede ejecutar herramientas que no existen en el entorno (como intentar llamar a `docker_logs` cuando solo existe `docker_list` y `docker_inspect`).

---

## 2. Solución Diseñada

### 2.1 Arquitectura del Nodo `evaluate_node` (`app/nodes/evaluate.py`)

```
[AgentState] ──┐
[Registry]   ──┼──> evaluate_node ──> [Prompt Evaluador + Catalog Schema] ──> [LLM]
[ChatModel]  ──┘                                                              │
                                                                              ▼
                                                    [JSON: goal_status, explanation, missing_caps]
                                                                              │
                                                                              ▼
                                           Mutaciones: evaluation_records, cognitive_steps, is_resolved
```

### 2.2 Formulación del System Prompt para Evaluación Semántica
El prompt instruye al LLM sobre su rol:
1. **Verificar Cumplimiento:** ¿La evidencia recopilada (salida de tools y contexto) responde completamente a la solicitud inicial del usuario?
   - Si sí ➔ `goal_status = "satisfied"`.
2. **Detectar Necesidad de Información Adicional:** ¿Hay un síntoma visible que justifique una inspección más profunda?
   - Comparar la herramienta necesaria contra la lista de herramientas disponibles (`available_tools`).
   - Si la herramienta requerida **está disponible** ➔ `goal_status = "needs_more_info"`, indicando `suggested_next_action`.
   - Si la herramienta requerida **NO está disponible** (ej. se necesitan logs pero no existe `docker:logs` ni equivalente en las herramientas disponibles) ➔ `goal_status = "blocked_missing_capability"`, agregándola a `missing_capabilities`.
3. **Formateo Estricto:** La respuesta debe ser un bloque JSON válido conteniendo `goal_status`, `explanation`, `missing_capabilities` y `suggested_next_action`.

### 2.3 Tolerancia a Fallos y Parsing Defensivo
- Si el LLM emite texto antes o después del JSON, o utiliza bloques Markdown ` ```json ... ``` `, una función de extracción por expresiones regulares recupera el objeto JSON.
- Si la respuesta del LLM no contiene un JSON válido o la llamada falla:
  - Si hay errores técnicos registrados en `state["errors"]` ➔ fallback a `GoalStatus.FAILED`.
  - Si las herramientas se completaron sin fallos técnicos ➔ fallback conservador a `GoalStatus.SATISFIED`.

### 2.4 Generación de Pasos Cognitivos y Auditoría
- Se añade un `CognitiveStepRecord` con `node="evaluate"`, título descriptivo de la iteración y el razonamiento del LLM, permitiendo su visualización transparente en la consola.

---

## 3. Plan de Verificación
1. **Tests Unitarios Específicos (`tests/test_node_evaluate.py`):**
   - Caso 1: Meta satisfecha (`GoalStatus.SATISFIED`).
   - Caso 2: Meta incompleta con herramienta disponible (`GoalStatus.NEEDS_MORE_INFO`).
   - Caso 3: Capability ausente (`GoalStatus.BLOCKED_MISSING_CAPABILITY` y `missing_capabilities=["docker:logs"]`).
   - Caso 4: Parsing defensivo ante JSON con backticks markdown.
   - Caso 5: Fallback defensivo ante fallo del modelo.
2. **Pipeline de Calidad (`bash scripts/check.sh`):** Ruff, MyPy estricto y Pytest pasando al 100%.
