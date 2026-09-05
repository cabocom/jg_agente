# Walkthrough Técnico — ISSUE-F06-T03

> **Issue ID:** `ISSUE-F06-T03`  
> **Fase:** `FASE 06`  
> **Componente:** `jg_agente.nodes.risk_assess`  
> **Fecha:** 5 de septiembre de 2026  

---

## 1. Resumen de Cambios

Se ha implementado el nodo de evaluación de riesgo y política HITL `risk_assess_node` en `app/nodes/risk_assess.py`, su exportación en `app/nodes/__init__.py`, la incorporación del campo `requires_approval` en `AgentState` (`app/models/state.py`), la delegación en `app/core/graph.py` (`default_risk_assess_node` y `route_after_risk_assess`) y una suite de 7 pruebas completas en `tests/test_node_risk_assess.py`.

---

## 2. Componentes Modificados y Nuevos

### 2.1. `app/models/state.py` [MODIFICADO]
- Añadido el atributo canónico `requires_approval: bool` en la sección de gobernanza HITL de `AgentState`.

### 2.2. `app/nodes/risk_assess.py` [NUEVO]
- Función `risk_assess_node(state: AgentState, registry: CapabilityRegistry | None = None, security_guard: SecurityGuard | None = None) -> dict[str, Any]`.
- Extracción flexible de acciones a evaluar (`ExecutionPlan.steps` o `tool_calls` directas).
- Interceptación y evaluación mediante `SecurityGuard.evaluate(...)`.
- Marcado de `requires_approval = True`, `human_intervention_required = True` y generación de `ApprovalRecord(status=PENDING)` cuando existe `RiskLevel.HIGH` o `RiskLevel.CRITICAL`.
- Bloqueo por seguridad (`PolicyDecision.DENY`) y activación de `circuit_breaker_active` ante inyecciones de comandos shell o violaciones de políticas.
- Emisión de auditoría estructurada con evento `risk_assessment_completed` y métricas de duración (`duration_ms`).

### 2.3. `app/nodes/__init__.py` [MODIFICADO]
- Exportación canónica de `risk_assess_node` en `__all__`.

### 2.4. `app/core/graph.py` [MODIFICADO]
- Conexión de `default_risk_assess_node` delegando en `risk_assess_node`.
- Ajuste en `route_after_risk_assess` para verificar explícitamente `state.get("requires_approval") is True` hacia `human_approval`.

### 2.5. `tests/test_node_risk_assess.py` [NUEVO]
- 7 casos de prueba verificando: pasos de alto riesgo, pasos críticos con pérdida de datos, planes seguros auto-autorizados, llamadas reactivas a herramientas, detección de inyección shell, preservación de aprobaciones y suspensión en checkpoint HITL en LangGraph.

---

## 3. Verificación de Calidad

Ejecución de `./scripts/check.sh`:
- **Ruff:** Formateo y linter conformes en los 53 archivos del proyecto.
- **MyPy:** Modo estricto superado con 0 errores en 53 archivos.
- **Pytest:** 180 pruebas superadas con éxito en 0.89s (100% pass).

---

## 4. Evidencia de Criterios de Aceptación

| Criterio de Aceptación | Estado | Evidencia |
| :--- | :---: | :--- |
| **Detección de RiskLevel >= HIGH** | ✅ Superado | `test_risk_assess_high_risk_plan_requires_approval` y `test_risk_assess_critical_risk_plan_requires_approval`. |
| **Marcado de requires_approval=True** | ✅ Superado | `result["requires_approval"] is True` verificado unitariamente y en snapshot. |
| **Enrutamiento hacia human_approval** | ✅ Superado | `test_risk_assess_graph_integration_routes_to_human_approval` verifica suspensión en checkpoint `human_approval`. |
| **Inicialización de ApprovalRecord** | ✅ Superado | Generación de `ApprovalRecord(status=PENDING)` ante acciones de riesgo elevado. |
| **Bloqueo ante inyección o violación** | ✅ Superado | `test_risk_assess_denies_shell_injection` valida veredicto `DENY` y activación de circuit breaker. |
