# Análisis Técnico: ISSUE-AGENTE-LOGIC-03

**Issue:** [jg_agente#68](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/68)  
**Título:** [AGENTE-LOGIC-03] Omisión de caller_permissions en execute_node Causa Denegaciones Falsas  
**Severidad:** 🟠 ALTO  
**Ubicación:** `jg_agente/app/nodes/execute.py:97-113, 255-268`  

---

## 1. Causa Raíz
En `jg_agente/app/nodes/execute.py`, al ejecutar cada paso de herramienta mediante `guard.execute_tool`:
1. Si la herramienta no cuenta con `bypass_approval=True` (por ejemplo, herramientas de riesgo bajo o medio que no requieren intervención humana HITL), `guard.execute_tool` delega en `self.evaluate(...)` para comprobar si el invocador posee los permisos requeridos por la herramienta (`required_permissions`).
2. Si `state` no preservó o no inicializó `caller_permissions` (por ejemplo, si se omitió al construir el `initial_state` en `executions.py` o si los nodos intermedios como `risk_assess` o `human_approval` no lo propagaron inmutablemente en sus mutaciones de estado), `caller_perms` resulta en una lista vacía `[]`.
3. `SecurityGuard.evaluate` compara los permisos requeridos contra la lista vacía de permisos del llamador y emite una denegación falsa (`PolicyDecision.DENY: Permisos insuficientes para ejecutar 'tool_name'`).

---

## 2. Solución Arquitectónica
1. **Helper Común para Resolución de Permisos (`resolve_caller_permissions`):**
   - Implementar una función canónica en `app/models/state.py` o en `app/security/guard.py` que resuelva de forma consistente los permisos del llamador a partir de `state.get("caller_permissions")`, `state["request"].user_context.permissions` y roles administrativos (`is_admin -> ["role:admin", "admin", "*"]`).
2. **Propagación Inmutable en `AgentState`:**
   - En `app/api/executions.py`: Inicializar formalmente `"caller_permissions": resolve_caller_permissions(initial_state)` al invocar `graph.ainvoke(initial_state, ...)`.
   - En `app/nodes/risk_assess.py`: Retornar `"caller_permissions": caller_perms` en el diccionario de mutación de estado.
   - En `app/nodes/human_approval.py`: Retornar `"caller_permissions": state.get("caller_permissions")` al reanudar o completar el nodo.
   - En `app/nodes/execute.py`: Asegurar que `caller_perms` se resuelva de forma robusta, se pase a `guard.execute_tool`, y se devuelva inmutablemente en `mutations["caller_permissions"]`.
3. **Pruebas Unitarias e Integradas:**
   - Crear pruebas en `tests/test_node_execute.py` verificando que una herramienta con `required_permissions` (y sin bypass HITL) se ejecuta exitosamente si el llamador posee el permiso en `state["caller_permissions"]` o en `user_context`, y que falla si carece de él.
