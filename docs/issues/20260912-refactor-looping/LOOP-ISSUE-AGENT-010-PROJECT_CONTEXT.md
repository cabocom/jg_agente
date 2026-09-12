# Contexto de Proyecto: [LOOP-ISSUE-AGENT-010] Topología cíclica en LangGraph, router de seguridad y erradicación de salidas JSON

## 1. Identificación y Estado
- **Issue ID:** LOOP-ISSUE-AGENT-010
- **GitLab Item:** [#51](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/51) (jg_agente)
- **Epic:** `EPIC-LOOPING-01` (Razonamiento Iterativo y Bucles de Pensamiento Proactivos)
- **Fase:** Fase 3 - Conexión de Grafo Cíclico, Guardarraíles y Síntesis Final
- **Prioridad:** High / Core Architecture
- **Complejidad Estimada:** L
- **Estado:** En Planificación

## 2. Alineación Arquitectónica
Este hito integra las piezas construidas en `LOOP-ISSUE-AGENT-008` (contratos y estados) y `LOOP-ISSUE-AGENT-009` (nodo `evaluate_node` con capability-awareness):

1. **Topología Cíclica en `app/core/graph.py`:**
   - Se incorpora el nodo `evaluate` tras `verify` (o tras `execute` si no hay `verifier`).
   - Se añade la arista condicional `route_after_evaluation` que permite retornar a `reason` para una nueva iteración de pensamiento si el objetivo requiere más información (`NEEDS_MORE_INFO`).
   - Si no se requiere más información, se alcanza el límite o hay bloqueo por capacidades (`BLOCKED_MISSING_CAPABILITY`, `SATISFIED`, `FAILED`), se transiciona hacia `conclude`.

2. **Guardarraíles Deterministas en Python:**
   - Control de presupuesto estricto: Si `iteration >= max_iterations` (default 3), el ciclo se interrumpe y transiciona inmediatamente a `conclude`, evitando bucles infinitos o consumo descontrolado de tokens.
   - Si se requiere rollback por fallo de verificación con compensación: transiciona a `rollback`.
   - Si falta una capacidad técnica: transiciona directamente a `conclude` para informar honestamente al operador.

3. **Incremento Controlado de Iteración en `app/nodes/reason.py`:**
   - Si el nodo de razonamiento es invocado en una iteración posterior (`evaluation_records` presente), incrementa `iteration` e inyecta la retroalimentación de la evaluación previa en la memoria del modelo para guiar el siguiente salto.

4. **Erradicación de Salidas JSON Crudas en `app/nodes/conclude.py`:**
   - Se prohíbe el volcado de diccionarios, arrays o strings crudos tipo `Resultado: {'containers': [...]}`.
   - Se prioriza la explicación en lenguaje natural generada por el nodo de evaluación semántica (`EvaluationRecord.explanation`), asegurando que el operador reciba una respuesta comprensible, profesional y redactada.

## 3. Criterios de Aceptación
- `GraphBuilder` compila el StateGraph conectando `evaluate` y la arista condicional `route_after_evaluation`.
- Pruebas unitarias de enrutamiento y guardarraíles:
  - Salto cíclico `evaluate -> reason` cuando `goal_status == NEEDS_MORE_INFO` e `iteration < max_iterations`.
  - Terminación forzada `evaluate -> conclude` cuando `iteration >= max_iterations`.
  - Terminación `evaluate -> conclude` cuando `goal_status == BLOCKED_MISSING_CAPABILITY`.
  - Terminación `evaluate -> conclude` cuando `goal_status == SATISFIED`.
- `conclude_node` entrega síntesis en lenguaje natural sin volcar JSON crudo.
- Suite de pruebas de regresión completa y `bash scripts/check.sh` pasando al 100%.
