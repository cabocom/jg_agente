# Análisis Técnico - Issue [AGENTE-SEC-06]

**Issue:** [jg_agente#62](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/62)  
**Título:** [AGENTE-SEC-06] Asignación de Permisos Wildcard a Administradores Invalida SecurityGuard  
**Severidad:** 🟡 MEDIO  
**CWE:** CWE-269 (Improper Privilege Management) / CWE-285 (Improper Authorization)  
**Ubicación:** `jg_agente/app/nodes/risk_assess.py:124-138`, `jg_agente/app/nodes/execute.py:97-109`, `jg_agente/app/security/guard.py:215-238`  

---

## 1. Contexto y Causa Raíz

En el sistema de evaluación de riesgos (`risk_assess_node`) y ejecución de herramientas (`execute_node`), la determinación de permisos del llamador (`caller_perms`) evaluaba el contexto de usuario mediante la siguiente condición:

```python
if req.user_context.role == "admin" or (
    getattr(req, "metadata", None) and req.metadata.get("user_role") == "admin"
):
    caller_perms = ["*"]
elif req.user_context.permissions:
    caller_perms = list(req.user_context.permissions)
```

### Problemas Identificados

1. **Sobre-escritura Ciega de Permisos Declarados:**
   Si la petición incluía scopes o permisos explícitos en `user_context.permissions`, estos quedaban anulados y reemplazados por un comodín global `["*"]` si el rol era `admin`.
2. **Confusión entre Autorización de Usuario (RBAC) e Invariantes de Seguridad:**
   La asignación de comodín global `["*"]` creaba la falsa presunción de inmunidad frente a las directivas de seguridad operativas del agente (`SecurityGuard`). En sistemas de agentes autónomos, la identidad o el rol privilegiado de un invocador nunca debe eludir los controles de integridad estructural del sistema (tales como inyección de comandos shell, acceso a rutas restringidas de sistema operativo `/etc`, `/proc`, ataques SSRF hacia metadatos cloud o puertas de gobernanza humana HITL para operaciones críticas).

---

## 2. Impacto de Seguridad

- **Pérdida de Defensa en Profundidad:**
  Si un administrador o un prompt malicioso instruía la ejecución de una herramienta con parámetros destructivos o malformados, la presunción de que el rol de administrador otorga bypass completo debilitaba las garantías de seguridad de la plataforma.
- **Acoplamiento de Autorización:**
  Falta de delimitación formal entre la validación de permisos de herramienta (RBAC) y las restricciones invariantes de seguridad (sandbox, path traversal, shell injection, SSRF y HITL).

---

## 3. Solución Implementada

Se estableció un desacople estricto entre la autorización RBAC de usuario y las restricciones invariantes de seguridad de la plataforma:

1. **Preservación y Fusión de Permisos Administrativos (`risk_assess.py` y `execute.py`):**
   - Se respetan íntegramente los permisos específicos definidos en `user_context.permissions`.
   - Si el rol es `admin`, se añaden los scopes de rol administrativo (`["role:admin", "admin", "*"]`) mediante unión de conjuntos, sin anular permisos específicos.

2. **Garantía Invariante en `SecurityGuard.evaluate` (`guard.py`):**
   - El chequeo de permisos (`caller_permissions`) valida **únicamente** si el invocador satisface los permisos requeridos por la herramienta (`required_permissions`).
   - Las validaciones posteriores de inyección shell (`SHELL_INJECTION_PATTERN`), directory traversal / rutas protegidas (`PROTECTED_SYSTEM_PATHS`), validación SSRF y evaluación de riesgo HITL (`RiskLevel.HIGH` / `RiskLevel.CRITICAL`) se ejecutan **incondicionalmente** para todos los llamadores, independientemente de que posean rol `admin` o comodín `*`.

3. **Cobertura de Pruebas Automatizadas:**
   - Nuevos casos de prueba en `test_security_guard.py` y `test_node_risk_assess.py` que demuestran que un administrador puede invocar herramientas protegidas por permisos, pero es bloqueado de forma determinista ante inyección shell o directory traversal.
