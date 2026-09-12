### ✅ Resolución y Cierre de Issue [AGENTE-SEC-05]

**Issue:** [jg_agente#61](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/61)
**Título:** [AGENTE-SEC-05] Bypass Masivo de Aprobación HITL Extiende Permisos a Todo el Plan
**Severidad:** 🟠 ALTO
**CWE:** CWE-269 (Improper Privilege Management)

---

#### 1. Causa Raíz Identificada
Al reanudarse una ejecución tras una intervención y aprobación humana (HITL), la bandera `bypass_approval = True` se propagaba de forma global a todos los pasos del plan (`step in steps_to_run`) en `app/nodes/execute.py`. Como consecuencia, `SecurityGuard.execute_tool` convalidaba automáticamente cualquier herramienta subsecuente o secundaria no revisada, permitiendo la escalada de privilegios a acciones destructivas no autorizadas por el operador.

#### 2. Cambios Implementados
- **Control Granular en el Modelo de Estado:**
  - Añadidos `approved_step_ids: list[str]` y `approved_tool_names: list[str]` a `ApprovalRecord` y al estado del agente `AgentState` (`app/models/state.py`).
- **Captura Precisa en `risk_assess_node`:**
  - Se identifican y persisten explícitamente los pasos y herramientas que originan la solicitud de aprobación (`app/nodes/risk_assess.py`).
- **Preservación y Propagación en `human_approval_node`:**
  - Se extraen y validan las listas aprobadas en la reanudación del ciclo cognitivo (`app/nodes/human_approval.py`).
- **Evaluación Granular en `execute_node`:**
  - Se sustituye el bypass indiscriminado por `step_bypass_approval`, comprobando si el paso actual o su herramienta figuran en las listas autorizadas (`app/nodes/execute.py`).
- **Defensa en Profundidad en `SecurityGuard`:**
  - `SecurityGuard.execute_tool` verifica de forma estricta que el paso o la herramienta invocada coincidan con las listas de aprobación (`effective_bypass`) antes de omitir la restricción de seguridad (`app/security/guard.py`).
- **Cobertura de Pruebas Automatizadas:**
  - Pruebas añadidas en `test_node_execute.py` verificando el bloqueo de herramientas críticas secundarias en planes con aprobación parcial y la correcta ejecución cuando todos los pasos son aprobados.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Formateo y análisis estático 100% limpios sin advertencias (`106 source files`).
- **Pytest:** Suite completa de `jg_agente` con 306 tests pasando exitosamente.
- **check.sh Global:** Verificación integral de `jg_agente`, `jg_dashboard` y Selenium E2E superada satisfactoriamente.
