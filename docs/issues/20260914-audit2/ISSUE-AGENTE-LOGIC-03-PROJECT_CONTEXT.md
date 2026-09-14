# Contexto del Proyecto: AGENTE-LOGIC-03

## 1. Módulo Afectado
- **Ruta principal:** `jg_agente/app/nodes/execute.py`
- **Componentes relacionados:** `jg_agente/app/nodes/risk_assess.py`, `jg_agente/app/nodes/human_approval.py`, `jg_agente/app/api/executions.py`, `jg_agente/app/models/state.py`
- **Severidad:** 🟠 ALTO

---

## 2. Principio Arquitectónico y de Seguridad: Trazabilidad Inmutable de Permisos
En una arquitectura desacoplada de Execution Plane, la identidad y los permisos del llamador (`caller_permissions`) provienen del plano de control (Control Plane / `jg_dashboard`) o de la autenticación de la solicitud (`AgentInput.user_context.permissions`).
Dichos permisos deben transmitirse de forma inmutable a lo largo de todo el ciclo de inferencia del grafo (`AgentState`) para que en cada evaluación de políticas de seguridad (tanto en `risk_assess` como en `execute`) las herramientas autorizadas cuenten con el contexto de permisos legítimo, evitando falsos positivos de `INSUFFICIENT_PERMISSIONS`.

---

## 3. Comportamiento Esperado tras la Remediación
- `caller_permissions` se inicializa formalmente en `initial_state` a partir de `input_data.user_context` (o `input_data.metadata`).
- Todos los nodos del grafo (`risk_assess`, `human_approval`, `execute`, etc.) preservan y reinyectan `caller_permissions` de forma inmutable en sus mutaciones de estado.
- `execute_node` resuelve de forma jerárquica y determinista `caller_permissions` y lo propaga a `guard.execute_tool`, permitiendo que herramientas con permisos requeridos (sin bypass de aprobación) se ejecuten con éxito si el operador cuenta con ellos.
