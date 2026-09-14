# Walkthrough de Implementación - Issue [AGENTE-SEC-06]

## Resumen de Cambios

Se ha desacoplado de manera formal la autorización RBAC del usuario de las restricciones invariantes de seguridad de la plataforma (`SecurityGuard`), asegurando que ni el rol `admin` ni permisos wildcard puedan vulnerar las protecciones contra inyección, directory traversal, SSRF o la gobernanza HITL.

### Modificaciones Realizadas

1. **`jg_agente/app/security/guard.py`:**
   - Se actualizó el paso 1 de `SecurityGuard.evaluate` para documentar y validar formalmente que los roles y wildcards (`role:admin`, `admin`, `*`) aplican única y exclusivamente al cumplimiento de permisos de herramienta (`effective_perms`).
   - Se garantiza que los pasos posteriores (inyección shell, directory traversal, SSRF y HITL) se ejecuten incondicionalmente para todos los usuarios.

2. **`jg_agente/app/nodes/risk_assess.py` y `jg_agente/app/nodes/execute.py`:**
   - Se sustituyó la sobre-escritura ciega `caller_perms = ["*"]` por una fusión estructurada: se preservan íntegramente los permisos específicos de `req.user_context.permissions` y, para administradores, se agregan los scopes de rol (`["role:admin", "admin", "*"]`).

3. **`jg_agente/tests/test_security_guard.py`:**
   - `test_admin_and_wildcard_caller_satisfies_required_permissions`: valida que los roles administrativos satisfagan los permisos requeridos.
   - `test_admin_caller_cannot_bypass_directory_traversal`: valida que un admin sea bloqueado con `PolicyDecision.DENY` al intentar acceder a rutas protegidas (`/etc/shadow`).
   - `test_admin_caller_cannot_bypass_shell_injection`: valida que un admin sea bloqueado con `PolicyDecision.DENY` ante inyección shell (`host; cat /etc/passwd`).
   - `test_admin_caller_cannot_bypass_hitl_governance`: valida que un admin deba someterse a HITL (`PolicyDecision.REQUIRE_HUMAN_APPROVAL`) para operaciones de riesgo crítico.

4. **`jg_agente/tests/test_node_risk_assess.py`:**
   - `test_risk_assess_blocks_admin_with_malicious_payload`: valida que en el nodo de grafo `risk_assess_node`, un usuario administrador con payload de traversal sea denegado y la ejecución marcada como `FAILED`.

---

## Verificación de Calidad

- **Pruebas Unitarias Directas:**
  ```bash
  ./jg_agente/.venv/bin/pytest jg_agente/tests/test_security_guard.py jg_agente/tests/test_node_risk_assess.py
  # 35 passed in 0.71s
  ```

- **Suite Completa de jg_agente:**
  ```bash
  ./jg_agente/.venv/bin/pytest jg_agente/tests
  # 311 passed in 33.36s
  ```

- **Linter y Análisis de Tipado:**
  ```bash
  ./jg_agente/.venv/bin/ruff check jg_agente/app jg_agente/tests jg_agente/plugins
  # All checks passed!
  ./jg_agente/.venv/bin/ruff format --check jg_agente/app jg_agente/tests jg_agente/plugins
  # 106 files already formatted
  ./jg_agente/.venv/bin/mypy --config-file jg_agente/pyproject.toml jg_agente/app jg_agente/tests jg_agente/plugins
  # Success: no issues found in 106 source files
  ```
