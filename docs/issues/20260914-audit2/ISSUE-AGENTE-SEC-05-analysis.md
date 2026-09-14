# Análisis Técnico - Issue [AGENTE-SEC-05]

**Issue:** [jg_agente#61](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/61)  
**Título:** [AGENTE-SEC-05] Bypass Masivo de Aprobación HITL Extiende Permisos a Todo el Plan  
**Severidad:** 🟠 ALTO  
**CWE:** CWE-269 (Improper Privilege Management)  
**Ubicación:** `jg_agente/app/nodes/execute.py:72`, `jg_agente/app/security/guard.py:342-385`  

---

## 1. Contexto y Descripción del Problema

En la arquitectura del agente inteligente, cuando una operación presenta un nivel de riesgo elevado (`RiskLevel.HIGH` o `RiskLevel.CRITICAL`), el nodo de evaluación de riesgo (`risk_assess`) y el módulo de seguridad (`SecurityGuard`) interceptan la ejecución emitiendo un veredicto de `REQUIRE_HUMAN_APPROVAL`. Esto suspende el grafo cognitivo mediante el mecanismo de interrupción HITL (Human-in-the-Loop) de LangGraph, a la espera de autorización por parte de un operador en el panel de control.

Tras la aprobación por parte del operador humano (vía `POST /executions/{thread_id}/approve`), la ejecución se reanudaba marcando la bandera `bypass_approval = True`.

### Vulnerabilidad Identificada

Previamente a esta corrección:
1. Al reanudar la ejecución, `execute.py` evaluaba `bypass_approval = is_plan_approved` y propagaba esa misma bandera de forma global e indiscriminada a **todos y cada uno de los pasos del plan (`step in steps_to_run`)**.
2. En `guard.py:execute_tool(...)`, si `bypass_approval` era `True`, se le concedían automáticamente al llamador todos los permisos requeridos por la herramienta (`caller_perms.extend(tool.required_permissions)`) y se omitía la exigencia de autorización humana para cualquier herramienta posterior.
3. Si el plan generado por el modelo contenía herramientas destructivas secundarias o no autorizadas que acompañaban a la herramienta legítima (por ejemplo, tras una manipulación del plan o inyección indirecta), estas se ejecutaban sin autorización explícita del operador humano.

---

## 2. Impacto de Seguridad

- **Escalada de Privilegios Post-Aprobación (CWE-269):** Un operador que aprobaba una acción de riesgo acotada (ej. `restart_service`) terminaba otorgando inadvertidamente autorización de ejecución a herramientas críticas secundarias en el mismo plan (ej. `drop_database` o `purge_storage`).
- **Pérdida de Trazabilidad e Intención:** El registro de auditoría no reflejaba si el operador realmente convalidó las herramientas secundarias o si el agente las ejecutó por contaminación del contexto de aprobación.

---

## 3. Estrategia de Solución

La remediación implementa el principio de privilegio mínimo y autorización granular por paso y por herramienta:

1. **Modelo de Estado (`app/models/state.py`):**
   - Incorporación de `approved_step_ids: list[str]` y `approved_tool_names: list[str]` tanto en `ApprovalRecord` como en el `TypedDict` `AgentState`.

2. **Detección Granular en `risk_assess_node` (`app/nodes/risk_assess.py`):**
   - Recolección precisa de los identificadores de paso (`step.step_id`) y nombres de herramientas (`step.tool_name`) que dispararon la necesidad de aprobación (`REQUIRE_HUMAN_APPROVAL` o `RiskLevel >= HIGH`).
   - Registro de estas listas en el estado inicial de `ApprovalRecord` (`status=PENDING`).

3. **Propagación en Reanudación (`app/nodes/human_approval.py`):**
   - Al procesar la decisión de reanudación (sea vía `Command(resume=...)` o estado previo), se preservan y propagan `approved_step_ids` y `approved_tool_names`.

4. **Validación Paso a Paso en `execute_node` (`app/nodes/execute.py`):**
   - Para cada paso del plan en ejecución, se calcula `step_bypass_approval`:
     - Si hay listas de aprobación (`approved_step_ids` o `approved_tool_names`), `step_bypass_approval = True` **únicamente** si el `step.step_id` o `step.tool_name` coincide con los aprobados.
     - Si no hay lista granular (retrocompatibilidad) y el plan consta de un único paso, se autoriza dicho paso único.
     - En cualquier otro caso con pasos múltiples no listados, `step_bypass_approval = False`.
   - Se pasan `step_id`, `approved_step_ids` y `approved_tool_names` a `guard.execute_tool(...)`.

5. **Defensa en Profundidad en `SecurityGuard.execute_tool` (`app/security/guard.py`):**
   - Cálculo de `effective_bypass`: si se especifican filtros (`approved_step_ids` o `approved_tool_names`), se valida que el paso o la herramienta invocada coincida con la lista autorizada.
   - Solo cuando `effective_bypass` es `True` se extiende la convalidación de permisos y se omite la interrupción `REQUIRE_HUMAN_APPROVAL`.
