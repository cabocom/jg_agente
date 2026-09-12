### ✅ Resolución y Cierre de Issue [AGENTE-SEC-04]

**Issue:** [jg_agente#60](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/60)
**Título:** [AGENTE-SEC-04] Auto-Asignación de Permisos a Invocadores no Autorizados en risk_assess_node
**Severidad:** 🟠 ALTO
**CWE:** CWE-285 (Improper Authorization)

---

#### 1. Causa Raíz Identificada
En `app/nodes/risk_assess.py`, si la petición del llamador no contenía permisos (`caller_perms` vacío), el código ejecutaba `if not caller_perms and tool: caller_perms = list(tool.required_permissions)`. Esto otorgaba automáticamente al llamador todos los permisos requeridos por la herramienta a ejecutar, anulando cualquier control RBAC y provocando que `guard.evaluate` siempre aprobase la acción.

#### 2. Cambios Implementados
- **Eliminación de la Auto-Concesión:** Suprimida la asignación automática de `tool.required_permissions` a `caller_perms`. Si el llamador carece de permisos, la lista permanece vacía y la acción es denegada con `PolicyDecision.DENY`.
- **Soporte de `caller_permissions` en `AgentState`:** Tipado el campo `caller_permissions: list[str] | None` en el `TypedDict` `AgentState` (`app/models/state.py`) para propagación a través del grafo cognitivo.
- **Resolución de Permisos en `risk_assess_node`:** Se extraen permisos prioritariamente de `state.get("caller_permissions")` o del contexto de usuario (`user_context.permissions` o wildcard `["*"]` para administradores).
- **Cobertura de Pruebas:**
  - Nuevas pruebas en `test_node_risk_assess.py` verificando el rechazo a invocadores sin permisos y la autorización correcta para operadores y administradores.
  - Ajuste en `test_graph_builder.py` para proporcionar contexto autorizado en el flujo de prueba HITL.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Tipado estricto y formato 100% limpios sin advertencias.
- **Pytest:** Suite completa de pruebas ejecutada y pasando exitosamente.
- **check.sh Global:** Verificación integral de `jg_agente`, `jg_dashboard` y Selenium E2E superada al 100%.
