# Análisis Técnico: [AGENTE-SEC-04] Auto-Asignación de Permisos a Invocadores no Autorizados en risk_assess_node

## Metadatos
- **Issue ID:** [jg_agente#60](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/60)
- **Severidad:** 🟠 ALTO
- **CWE:** CWE-285 (Improper Authorization)
- **Componentes Afectados:**
  - `jg_agente/app/nodes/risk_assess.py` (`risk_assess_node`, resolución de `caller_perms`)
  - `jg_agente/app/models/state.py` (`AgentState.caller_permissions`)
  - `jg_agente/tests/test_node_risk_assess.py`
  - `jg_agente/tests/test_graph_builder.py`
- **Fecha:** Septiembre 2026

---

## 1. Descripción del Problema y Causa Raíz

En el nodo de evaluación de riesgos (`app/nodes/risk_assess.py`), existía una lógica de asignación por defecto que concedía automáticamente al llamador todos los permisos requeridos por la herramienta que se disponía a evaluar:

```python
# Código vulnerable anterior (app/nodes/risk_assess.py):
caller_perms: list[str] = []
if req and req.user_context:
    if req.user_context.role == "admin" or (
        getattr(req, "metadata", None) and req.metadata.get("user_role") == "admin"
    ):
        caller_perms = ["*"]
    elif req.user_context.permissions:
        caller_perms = list(req.user_context.permissions)
if not caller_perms and tool:
    caller_perms = list(tool.required_permissions)  # <--- VULNERABILIDAD CWE-285
```

### Mecánica del Fallo:
1. Si una petición carecía de `user_context` o el llamador poseía una lista vacía de permisos (`caller_permissions`), el condicional `if not caller_perms and tool:` se evaluaba como verdadero.
2. Inmediatamente después, `caller_perms` era rellenado con `list(tool.required_permissions)`.
3. Al invocar posteriormente `guard.evaluate(tool=tool, caller_permissions=caller_perms)`, `SecurityGuard` comparaba los permisos requeridos por la herramienta contra los permisos del llamador.
4. Dado que el llamador había recibido de forma ilegítima los mismos permisos exigidos por la herramienta, la lista `missing_perms` resultaba vacía y `SecurityGuard` aprobaba la verificación de permisos sin oposición.

---

## 2. Impacto Técnico y de Seguridad

- **Integridad y Control de Acceso:** Severidad ALTA (CWE-285).
- Anulación completa del control de acceso RBAC (*Role-Based Access Control*) a nivel de herramientas en el Execution Plane.
- Cualquier usuario no autenticado o con permisos restringidos (e.g. rol `viewer`) podía solicitar la ejecución de herramientas privilegiadas (como reinicios de contenedores `docker:restart`, despliegues o accesos a bases de datos) eludiendo la compuerta de autorización.

---

## 3. Solución Arquitectónica Implementada

### A. Eliminación de la Auto-Concesión
Se suprimió por completo el bloque:
```python
# ELIMINADO:
# if not caller_perms and tool:
#     caller_perms = list(tool.required_permissions)
```
Si el llamador no acredita permisos explícitos ni rol `admin`, `caller_perms` permanece como lista vacía `[]`. Si la herramienta exige permisos (`tool.required_permissions` no vacío), `SecurityGuard.evaluate` deniega la acción de forma determinista con `PolicyDecision.DENY` indicando `Permisos insuficientes. Faltan: [...]`.

### B. Formalización de `caller_permissions` en `AgentState`
Para asegurar la observabilidad y trazabilidad inmutable de los permisos a través del grafo de LangGraph, se añadió el campo `caller_permissions: list[str] | None` en el `TypedDict` `AgentState` (`app/models/state.py`).

### C. Resolución Jerárquica de Permisos
En `risk_assess_node`:
1. Primero se verifica si el estado incluye `state.get("caller_permissions")`.
2. Si no, se extrae de `req.user_context`:
   - Rol `admin` (o metadato equivalente): otorga wildcard `["*"]`.
   - Permisos explícitos: `list(req.user_context.permissions)`.
3. En ausencia de permisos legítimos, la lista permanece vacía y la compuerta RBAC deniega la operación si la herramienta exige permisos.

---

## 4. Verificación y Cobertura de Pruebas

Se añadieron pruebas unitarias en `jg_agente/tests/test_node_risk_assess.py`:
- `test_risk_assess_denies_unauthorized_caller_without_permissions`: Verifica que un usuario sin permisos sea denegado (`PolicyDecision.DENY`, `status == FAILED`, motivo "Permisos insuficientes").
- `test_risk_assess_allows_authorized_caller_with_permission`: Verifica que un usuario con el permiso explícito sea autorizado.
- `test_risk_assess_allows_admin_caller_with_wildcard`: Verifica que un usuario admin obtenga wildcard y sea autorizado.
- Se actualizó `test_graph_builder.py` para reflejar un invocador autorizado en el test de interrupción HITL.
