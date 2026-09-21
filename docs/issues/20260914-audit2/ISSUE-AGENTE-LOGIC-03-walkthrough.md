# Walkthrough - [AGENTE-LOGIC-03] Omisión de caller_permissions en execute_node Causa Denegaciones Falsas

## Resumen Ejecutivo

- **Issue:** [jg_agente#68](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/68) - `[AGENTE-LOGIC-03] Omisión de caller_permissions en execute_node Causa Denegaciones Falsas`
- **Severidad:** 🟠 ALTO
- **Componentes Afectados:**
  - [`app/models/state.py`](../../../app/models/state.py)
  - [`app/api/executions.py`](../../../app/api/executions.py)
  - [`app/nodes/risk_assess.py`](../../../app/nodes/risk_assess.py)
  - [`app/nodes/human_approval.py`](../../../app/nodes/human_approval.py)
  - [`app/nodes/execute.py`](../../../app/nodes/execute.py)
  - [`tests/test_node_execute.py`](../../../tests/test_node_execute.py)

---

## Causa Raíz

En el ciclo cognitivo de ejecución de herramientas:
1. Al crear el estado inicial en `executions.py`, la clave `caller_permissions` no se poblaba a partir de `request.user_context` o `metadata`.
2. Durante las transiciones entre nodos (`risk_assess`, `human_approval`, `execute`), la lista de permisos no se retornaba en las mutaciones del diccionario de estado de LangGraph, por lo que en reanudaciones o ejecuciones directas sin bypass de aprobación (`bypass_approval=False`), `SecurityGuard` recibía una lista vacía de permisos (`caller_permissions=[]`).
3. Herramientas legítimas que requerían permisos específicos (RBAC) eran rechazadas con veredicto `DENY: Permisos insuficientes...` de forma espuria.

---

## Solución Implementada

1. **Función Centralizada y Canónica de Resolución de Permisos:**
   - En [`app/models/state.py`](../../../app/models/state.py), se implementó `resolve_caller_permissions(state: AgentState | dict[str, Any]) -> list[str]`.
   - Resuelve permisos con precedencia determinista:
     1. `state.get("caller_permissions")`
     2. `request.user_context.permissions` (con expansión de rol admin `["role:admin", "admin", "*"]`)
     3. `request.metadata.get("caller_permissions")`
     4. Default seguro: `[]`

2. **Inyección en Estado Inicial:**
   - En [`app/api/executions.py`](../../../app/api/executions.py), `initial_state` incluye `"caller_permissions": resolve_caller_permissions({"request": input_data})`.

3. **Propagación Inmutable a lo Largo del Grafo:**
   - En [`app/nodes/risk_assess.py`](../../../app/nodes/risk_assess.py): unificación mediante `resolve_caller_permissions(state)` y retorno explícito en `update_state["caller_permissions"]`.
   - En [`app/nodes/human_approval.py`](../../../app/nodes/human_approval.py): preservación de `caller_permissions` en los tres caminos de retorno (pre-aprobado, pre-rechazado y reanudación con decisión).
   - En [`app/nodes/execute.py`](../../../app/nodes/execute.py): resolución unificada y retorno en `mutations["caller_permissions"]`.

4. **Cobertura de Pruebas Automatizadas:**
   - Nuevos tests añadidos a [`tests/test_node_execute.py`](../../../tests/test_node_execute.py):
     - `test_execute_node_propagates_caller_permissions_and_allows_rbac_tool`: verificación de ejecución exitosa con permisos en estado y trazabilidad en retorno.
     - `test_execute_node_denies_tool_when_caller_permissions_missing`: denegación legítima cuando faltan permisos requeridos.
     - `test_execute_node_resolves_caller_permissions_from_user_context`: extracción transparente desde `request.user_context`.
     - `test_resolve_caller_permissions_utility`: cobertura unitaria para todos los casos jerárquicos de resolución.
