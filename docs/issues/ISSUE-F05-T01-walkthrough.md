# Walkthrough Técnico: ISSUE-F05-T01 — Implementación del GraphBuilder agnóstico de LangGraph

> **Issue ID:** `ISSUE-F05-T01`  
> **Fase:** `FASE 05`  
> **Componente:** `jg_agente.core.graph`  
> **Fecha:** 4 de septiembre de 2026  

---

## 1. Resumen de Cambios

Se ha implementado el ensamblador dinámico y agnóstico del grafo de LangGraph en `app/core/graph.py` junto con sus exportaciones en `app/core/__init__.py` y la suite exhaustiva de pruebas en `tests/test_graph_builder.py`.

### Componentes Creados y Modificados:
1. **`app/core/graph.py`:**
   - `GraphTopologyInfo`: Modelo Pydantic con la descripción estructural de la topología ensamblada.
   - Nodos canónicos asíncronos por defecto:
     - `default_observe_node`: Telemetría y estado de entorno con `ObserverEngine`.
     - `default_reason_node`: Inferencia de intención (`IntentModel`) y decisión de flujo.
     - `default_plan_node`: Formulación de `ExecutionPlan` con `PlannerEngine`.
     - `default_risk_assess_node`: Evaluación de riesgo operativo y HITL con `SecurityGuard`.
     - `default_human_approval_node`: Punto de pausa/aprobación humana.
     - `default_execute_node`: Invocación sandboxed de herramientas mediante `SecurityGuard.execute_tool()`.
     - `default_verify_node`: Verificación post-ejecución con `VerifierEngine`.
     - `default_rollback_node`: Compensación reversa de acciones reversibles.
     - `default_conclude_node`: Consolidación final y emisión de `AgentOutput` / `AgentExecutionStatus`.
   - Enrutadores condicionales agnósticos:
     - `route_after_reason`: Conecta a `conclude`, `plan` o `execute`.
     - `route_after_plan`: Conecta a `risk_assess` o `execute`.
     - `route_after_risk_assess`: Conecta a `human_approval`, `execute` o `conclude`.
     - `route_after_human_approval`: Conecta a `execute` o `conclude`.
     - `route_after_execute`: Conecta a `verify` o `conclude`.
     - `route_after_verify`: Conecta a `rollback` o `conclude`.
   - `GraphBuilder`: Clase orquestadora con métodos `get_topology()` y `build()`.
   - `build_agent_graph`: Función helper de conveniencia para arranque.
2. **`app/security/guard.py`:**
   - Se añadió el parámetro `bypass_approval: bool = False` a `execute_tool()` para admitir ejecuciones explícitamente autorizadas por aprobación humana (HITL).
3. **`app/core/__init__.py`:**
   - Exportación de `GraphBuilder`, `GraphTopologyInfo` y `build_agent_graph`.
4. **`tests/test_graph_builder.py`:**
   - 8 tests cubriendo topología mínima, topología completa (9 nodos), HITL con interrupción en checkpointer y reanudación, rollback ante fallos de verificación, validación de AST para agnosticismo radical y sobreescritura de nodos.
5. **`docs/graph.md`:**
   - Documentación técnica detallada con diagramas de flujo Mermaid, tablas de contratos y ejemplos de código.

---

## 2. Resultados de Verificación

```bash
$ ./scripts/check.sh
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
39 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 39 source files

3️⃣  [Pytest] Ejecución de suite de tests...
........................................................................ [ 53%]
...............................................................          [100%]
135 passed in 0.90s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```

---

## 3. Estado de Criterios de Aceptación

- [x] **StateGraph compilado generado:** `GraphBuilder.build()` compila un `CompiledStateGraph` sobre `AgentState`.
- [x] **StateSnapshot funcional:** `graph.get_state(config)` / `graph.aget_state(config)` retorna el snapshot completo de estado con soporte para `MemorySaver` o `PostgresSaver`.
- [x] **Cero condicionales de dominio:** No existen cadenas ni bifurcaciones `if conversational` ni `if devops` en el código.
