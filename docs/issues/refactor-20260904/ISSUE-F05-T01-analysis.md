# Análisis Técnico: ISSUE-F05-T01 — Implementación del GraphBuilder agnóstico de LangGraph

> **Issue ID:** `ISSUE-F05-T01`  
> **Fase:** `FASE 05` — Ensamblado del Grafo LangGraph y Nodos Base  
> **Prioridad:** Critical  
> **Complejidad Estimada:** L  
> **Dependencias:** `ISSUE-F02-T04` (AgentState), `ISSUE-F04-T02` (CapabilityRegistry)  
> **Fecha:** 4 de septiembre de 2026  

---

## 1. Contexto y Objetivos

El Execution Plane (`jg_agente`) requiere un mecanismo dinámico y determinista para ensamblar el motor de orquestación cognitiva en tiempo de arranque (**Boot time**). El orquestador subyacente es **LangGraph** (`StateGraph[AgentState]`), el cual opera sobre el estado global desacoplado definido en la Fase 02.

El principal desafío arquitectónico es garantizar el **Agnosticismo Radical**:
- El ensamblador no puede contener condicionales `if conversational` o `if devops`.
- La topología del grafo debe emerger exclusivamente como resultado de la introspección de capacidades registradas en [`CapabilityRegistry`](../plugins.md).
- El grafo resultante debe compilarse con persistencia activa (garantizando soporte funcional para `StateSnapshot` vía `graph.get_state(config)`).

---

## 2. Criterios de Aceptación y Validación

| Criterio | Estado | Evidencia / Implementación |
| :--- | :---: | :--- |
| `GraphBuilder` genera un `StateGraph` compilado funcional | ✅ CUMPLIDO | Clase `GraphBuilder` en `app/core/graph.py` compila `StateGraph[AgentState]`. |
| Soporte de `StateSnapshot` nativo y consultable | ✅ CUMPLIDO | `graph.get_state(config)` y `graph.aget_state(config)` retornan instancias `StateSnapshot`. Si no se provee checkpointer externo, se inicializa `MemorySaver` por defecto. |
| Ausencia absoluta de condicionales de dominio (`conversational`/`devops`) | ✅ CUMPLIDO | Validado mediante inspección léxica y análisis de AST en `tests/test_graph_builder.py::TestGraphBuilderAgnosticism`. |
| Conexión condicional de nodos según capacidades | ✅ CUMPLIDO | Conexión dinámica de `observe`, `plan`, `risk_assess`, `human_approval`, `verify` y `rollback`. |
| Nodos canónicos troncales garantizados | ✅ CUMPLIDO | `reason`, `execute` y `conclude` siempre presentes. |

---

## 3. Decisiones de Diseño

1. **Topología Dinámica por Inspección de Capacidades:**
   - Si `registry.get_observer()` está presente → `START -> observe -> reason`. Si no → `START -> reason`.
   - Si `registry.get_planner()` está presente → `reason -> plan -> (risk_assess o execute)`.
   - Si existen herramientas de riesgo `HIGH`/`CRITICAL` → se intercalan `risk_assess` y `human_approval` (con soporte para `interrupt_before=["human_approval"]`).
   - Si `registry.get_verifier()` está presente → `execute -> verify`.
   - Si existen herramientas con `reversible=True` y falla la verificación → `verify -> rollback -> conclude`.
2. **Nodos Asíncronos Nativos:**
   - Todos los handlers internos de nodos se declaran e invocan como corrutinas asíncronas (`async def`), integrándose de forma limpia con `ainvoke` y FastAPI `asyncio`.
3. **Manejo de Permisos en HITL Aprobado:**
   - Cuando una operación de alto riesgo es pausada en `human_approval` y reanudada con `approval.status == ApprovalStatus.APPROVED`, el `SecurityGuard` asume los permisos requeridos por la herramienta autorizada explícitamente (`bypass_approval=True`).

---

## 4. Pruebas y Cobertura

La suite en [`tests/test_graph_builder.py`](../../tests/test_graph_builder.py) valida:
1. `TestGraphBuilderMinimal`: Ensamblado de topología mínima (`reason`, `execute`, `conclude`) y recuperación de `StateSnapshot`.
2. `TestGraphBuilderFullTopology`: Registro completo de observer, planner, verifier, herramientas reversibles y de alto riesgo, validando los 9 nodos.
3. `TestGraphBuilderHITL`: Interrupción real en checkpointer (`interrupt_before=["human_approval"]`), inspección de estado pausado (`snapshot.next == ('human_approval',)`), actualización con `ApprovalRecord(status=APPROVED)` y reanudación exitosa.
4. `TestGraphBuilderRollback`: Disparo de compensación (`rollback`) ante fallos en `verify`.
5. `TestGraphBuilderAgnosticism`: Análisis de AST y tokens léxicos para garantizar cero bifurcaciones de dominio.
6. `TestGraphBuilderNodeOverrides`: Posibilidad de sobreescribir handlers preservando la topología.
