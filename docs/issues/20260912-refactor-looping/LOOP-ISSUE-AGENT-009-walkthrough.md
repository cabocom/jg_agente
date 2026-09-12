# Walkthrough Técnico: [LOOP-ISSUE-AGENT-009] Nodo de evaluación semántica (evaluate_node) y Capability-Awareness

## 1. Resumen de Implementación
En cumplimiento del issue [#50](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/50) de `jg_agente`, se implementó el nodo cognitivo de reflexión y auditoría de objetivos:

1. **Nuevo Nodo `app/nodes/evaluate.py`:**
   - Función principal asíncrona: `evaluate_node(state, registry, llm=None)`.
   - Recupera el objetivo original del usuario (`request.prompt`) y el catálogo de herramientas disponibles (`registry.list_tools()`).
   - Construye un contexto sintético con los pasos ejecutados (`StepExecutionRecord`), observaciones recibidas (`ToolMessage`) y errores detectados.
   - Invoca al modelo LLM activo configurado en el agente (`get_chat_model()` con Groq `openai/gpt-oss-120b`).

2. **Lógica de Capability-Awareness:**
   - Si el agente identifica que para diagnosticar un problema (ej. contenedor reiniciándose o CrashLoopBackOff) necesita una capacidad ausente en su catálogo (como `docker:logs`), emite el estado `GoalStatus.BLOCKED_MISSING_CAPABILITY`.
   - Genera una explicación constructiva y honesta para el operador humano detallando el hallazgo y la capacidad técnica faltante (`missing_capabilities`).
   - Auto-corrección consistente: si el modelo sugiere una herramienta adicional en `suggested_next_action` que no se encuentra en el catálogo registrado, el nodo la clasifica automáticamente como capacidad faltante y marca el estado como `BLOCKED_MISSING_CAPABILITY`.

3. **Trazabilidad y Observabilidad en Consola:**
   - Emite un `EvaluationRecord` estructurado en `state["evaluation_records"]`.
   - Emite un `CognitiveStepRecord` que se visualiza como un salto cognitivo en la consola web de `jg_dashboard`.
   - Registra el evento en `state["audit_trail"]` con duración en milisegundos y metadatos completos.

4. **Resiliencia y Parsing Defensivo:**
   - Extracción de JSON limpia bloques markdown ````json ... ```` o texto envolvente.
   - En caso de indisponibilidad del proveedor LLM, aplica un fallback defensivo sin interrumpir el ciclo del agente.

5. **Exportación en `app/nodes/__init__.py`:**
   - `evaluate_node` reexportado en el paquete central de nodos.

---

## 2. Suite de Pruebas Automatizadas (`tests/test_node_evaluate.py`)
Se implementaron 6 pruebas unitarias completas:
1. `test_evaluate_node_satisfied`: Evaluación de meta cumplida (`GoalStatus.SATISFIED` e `is_resolved=True`).
2. `test_evaluate_node_needs_more_info`: Solicitud de paso adicional con herramienta disponible (`docker:inspect`).
3. `test_evaluate_node_blocked_missing_capability`: Detección de falta de `docker:logs` ante contenedor en bucle de reinicio.
4. `test_evaluate_node_auto_corrects_unregistered_suggested_tool`: Auto-corrección de herramienta no registrada sugerida por el LLM.
5. `test_evaluate_node_markdown_json_cleaning`: Limpieza de bloques markdown ```json.
6. `test_evaluate_node_fallback_on_exception`: Resiliencia defensiva ante fallo del LLM.
