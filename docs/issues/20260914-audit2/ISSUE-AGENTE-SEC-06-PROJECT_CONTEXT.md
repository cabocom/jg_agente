# Contexto de Proyecto - Issue [AGENTE-SEC-06]

## Información General
- **Repositorio:** `jg_agente`
- **Issue:** [jg_agente#62](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/62)
- **Título:** [AGENTE-SEC-06] Asignación de Permisos Wildcard a Administradores Invalida SecurityGuard
- **Severidad:** 🟡 MEDIO
- **CWE:** CWE-269 (Improper Privilege Management) / CWE-285 (Improper Authorization)

## Módulos y Archivos Involucrados
1. `jg_agente/app/security/guard.py`:
   - `SecurityGuard.evaluate`: desacople explícito entre la verificación de permisos RBAC del llamador y los controles invariantes de la plataforma (inyección shell, directory traversal, SSRF y puertas HITL).
2. `jg_agente/app/nodes/risk_assess.py`:
   - `risk_assess_node`: conservación de los permisos específicos de `user_context.permissions` y agregación controlada de scopes administrativos (`role:admin`, `admin`, `*`).
3. `jg_agente/app/nodes/execute.py`:
   - `execute_node`: resolución coherente de `caller_perms` preservando permisos explícitos y agregando scopes administrativos.
4. `jg_agente/tests/test_security_guard.py`:
   - Casos de prueba que validan la autorización RBAC para administradores y el bloqueo estricto e ineludible ante inyección, traversal o riesgo crítico.
5. `jg_agente/tests/test_node_risk_assess.py`:
   - Caso de prueba de integración validando que un administrador sea bloqueado en `risk_assess_node` si su payload contiene transgresiones de seguridad invariantes.
