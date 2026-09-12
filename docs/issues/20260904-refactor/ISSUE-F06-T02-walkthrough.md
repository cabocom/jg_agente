# Walkthrough Técnico — ISSUE-F06-T02

> **Issue ID:** `ISSUE-F06-T02`  
> **Fase:** `FASE 06`  
> **Componente:** `jg_agente.nodes.plan`  
> **Fecha:** 5 de septiembre de 2026  

---

## 1. Resumen de Cambios

Se ha implementado el nodo opcional de LangGraph `plan_node` en `app/nodes/plan.py`, su exportación en `app/nodes/__init__.py`, la incorporación del campo `dependencies` en `PlanStep` (`app/models/state.py`), la delegación en `app/core/graph.py` (`default_plan_node`) y una suite de 8 pruebas exhaustivas en `tests/test_node_plan.py`.

---

## 2. Componentes Modificados y Nuevos

### 2.1. `app/models/state.py` [MODIFICADO]
- Añadido el atributo `dependencies: list[str] = Field(default_factory=list, description="Lista de step_ids previos requeridos antes de este paso")` a `PlanStep`.

### 2.2. `app/nodes/plan.py` [NUEVO]
- Función `plan_node(state: AgentState, registry: CapabilityRegistry | None = None, engine: PlannerEngine | BaseEngine | None = None) -> dict[str, Any]`.
- Búsqueda polimórfica de métodos de planificación (`create_plan`, `plan`, `build_plan`, `generate_plan`).
- Soporte transparente para corrutinas asíncronas y funciones síncronas.
- Transformación y validación automática de retornos tipo `ExecutionPlan`, `dict` o `list[PlanStep]`.
- Cálculo del nivel de riesgo acumulado (`estimated_risk`).
- Resiliencia ante excepciones operacionales emitiendo `ExecutionError(component="plan", fatal=False)` y derivando en un plan fallback seguro.
- Emisión de auditoría inmutable `planning_completed` con duración en milisegundos (`duration_ms`).

### 2.3. `app/nodes/__init__.py` [MODIFICADO]
- Exportación canónica de `plan_node` en `__all__`.

### 2.4. `app/core/graph.py` [MODIFICADO]
- Conexión de `default_plan_node` para delegar en `plan_node(state, registry=registry)`.

### 2.5. `tests/test_node_plan.py` [NUEVO]
- 8 casos de prueba que cubren: motores asíncronos y síncronos, conversión de diccionarios, conversión de listas de pasos, planes contingentes/fallback, cómputo estricto de riesgo, captura de excepciones e integración con grafo compilado de LangGraph.

---

## 3. Verificación de Calidad

Ejecución de `./scripts/check.sh`:
- **Ruff:** Formateo y linter 100% limpios en los 51 archivos del proyecto.
- **MyPy:** Tipado estricto superado con 0 errores en 51 archivos.
- **Pytest:** 173 pruebas superadas con éxito en 1.08s (100% pass).

---

## 4. Evidencia de Criterios de Aceptación

| Criterio de Aceptación | Estado | Evidencia |
| :--- | :---: | :--- |
| **Generación de ExecutionPlan estructurado** | ✅ Superado | `test_plan_node_with_async_planner` y `test_plan_node_converts_dict_plan`. |
| **Pasos y herramientas previstas** | ✅ Superado | Cada paso (`PlanStep`) define `tool_name`, `tool_args`, `risk_level` y `reversible`. |
| **Dependencias explícitas entre pasos** | ✅ Superado | Campo `dependencies: list[str]` en `PlanStep` verificado en tests (`step.dependencies == ["step-1"]`). |
| **Integración limpia en AgentState** | ✅ Superado | `state["plan"]` contiene la instancia `ExecutionPlan` y se consume limpiamente en `execute_node` y `GraphBuilder`. |
| **Tolerancia a fallos y resiliencia** | ✅ Superado | `test_plan_node_captures_engine_exception` valida contención y emisión de `ExecutionError`. |
