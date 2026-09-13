### ✅ Resolución y Cierre de Issue [AGENTE-SEC-06]

**Issue:** [jg_agente#62](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/62)
**Título:** [AGENTE-SEC-06] Asignación de Permisos Wildcard a Administradores Invalida SecurityGuard
**Severidad:** 🟡 MEDIO
**CWE:** CWE-269 (Improper Privilege Management) / CWE-285 (Improper Authorization)

---

#### 1. Causa Raíz Identificada
En `app/nodes/risk_assess.py` y `app/nodes/execute.py`, los usuarios con rol `admin` recibían ciegamente una lista con comodín `caller_perms = ["*"]`. Esto anulaba cualquier permiso específico provisto en `user_context.permissions` y fomentaba la presunción de que el rol de administrador eludía las comprobaciones de seguridad de `SecurityGuard`.

#### 2. Cambios Implementados
- **Desacople Formal de Autorización e Invariantes:**
  - En `app/security/guard.py`, se delimitó de forma estricta que la verificación de permisos del llamador (`caller_permissions`) únicamente convalidará la tenencia de permisos requeridos por la herramienta (RBAC). Las comprobaciones invariantes de seguridad (inyección shell, directory traversal, SSRF y la compuerta HITL para operaciones de alto riesgo) se ejecutan de manera ineludible para cualquier usuario, incluidos los administradores.
- **Preservación y Fusión de Permisos:**
  - En `app/nodes/risk_assess.py` y `app/nodes/execute.py`, se preservan íntegramente los permisos específicos de `req.user_context.permissions` y, para administradores, se añaden los scopes de rol administrativo (`["role:admin", "admin", "*"]`) mediante unión de conjuntos.
- **Pruebas de Seguridad Automatizadas:**
  - Nuevos tests en `test_security_guard.py` verificando que un invocador admin satisfaga permisos RBAC pero sea bloqueado con `DENY` ante inyección shell o directory traversal (`/etc/shadow`), y forzado a `REQUIRE_HUMAN_APPROVAL` ante herramientas de riesgo crítico.
  - Test de integración en `test_node_risk_assess.py` verificando el bloqueo a nivel de grafo cognitivo.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Formato y análisis estático 100% limpios sin advertencias en los 106 archivos.
- **Pytest:** Suite completa con 311 tests pasando exitosamente.
- **check.sh Global:** Verificación integral de `jg_agente`, `jg_dashboard` y Selenium E2E superada al 100%.
