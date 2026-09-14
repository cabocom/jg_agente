# Contexto de Proyecto - Issue [AGENTE-SEC-05]

## Información General
- **Repositorio:** `jg_agente`
- **Issue:** [jg_agente#61](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/61)
- **Título:** [AGENTE-SEC-05] Bypass Masivo de Aprobación HITL Extiende Permisos a Todo el Plan
- **Severidad:** 🟠 ALTO
- **CWE:** CWE-269 (Improper Privilege Management)

## Módulos y Archivos Involucrados
1. `jg_agente/app/models/state.py`:
   - `ApprovalRecord`: adición de `approved_step_ids` y `approved_tool_names`.
   - `AgentState`: adición de claves `approved_step_ids` y `approved_tool_names`.
2. `jg_agente/app/nodes/risk_assess.py`:
   - Detección de pasos y herramientas de alto riesgo que demandan aprobación previa.
   - Preservación de identificadores canónicos en `ApprovalRecord` y estado.
3. `jg_agente/app/nodes/human_approval.py`:
   - Extracción y propagación de identificadores de pasos y herramientas aprobadas durante la reanudación del grafo cognitivo.
4. `jg_agente/app/nodes/execute.py`:
   - Enrutamiento y evaluación granular de bypass por paso en el bucle de ejecución del plan.
   - Prevención de herencia masiva de `bypass_approval` en planes multipaso.
5. `jg_agente/app/security/guard.py`:
   - `SecurityGuard.execute_tool`: cálculo de `effective_bypass` basado en pertenencia a listas aprobadas.
6. `jg_agente/tests/test_node_execute.py`:
   - Pruebas unitarias y de integración que verifican el bloqueo de pasos no autorizados y la ejecución correcta de pasos aprobados.
