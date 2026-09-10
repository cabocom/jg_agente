### Resumen de Implementación — ISSUE-F06-T02

Se ha completado la implementación del nodo opcional de LangGraph `plan_node` en `jg_agente`, permitiendo transformar intenciones operativas complejas en planes de ejecución estructurados con dependencias secuenciales y evaluación rigurosa del riesgo acumulado.

#### 1. Componentes Desarrollados y Modificados
- **`app/models/state.py`:**
  - Incorporación del campo `dependencies: list[str] = Field(default_factory=list)` al contrato canónico `PlanStep`.
- **`app/nodes/plan.py` & `app/nodes/__init__.py`:**
  - Implementación de la función asíncrona `plan_node(state, registry, engine)`.
  - Invocación dinámica y polimórfica de métodos `create_plan`, `plan`, `build_plan` o `generate_plan` de `PlannerEngine`.
  - Soporte transparente para corrutinas asíncronas y funciones síncronas con o sin inyección del estado `AgentState`.
  - Conversión flexible de retornos tipo `ExecutionPlan`, diccionarios planos o secuencias de `PlanStep`.
  - Recálculo dinámico de `estimated_risk` asegurando consistencia con el paso de mayor riesgo operacional.
  - Generación de plan fallback seguro a partir del catálogo de herramientas e intención cuando no existe un motor registrado.
  - Contención segura de excepciones operacionales registrando `ExecutionError(fatal=False)` en `state["errors"]`.
  - Emisión de auditoría estructurada con evento `planning_completed` en `state["audit_trail"]`.
- **`app/core/graph.py`:**
  - Conexión de `default_plan_node` delegando directamente en `plan_node`.
- **`tests/test_node_plan.py`:**
  - Suite de 8 pruebas unitarias e integradas validando motores asíncronos/síncronos, conversión de diccionarios, dependencias de pasos, planes contingentes, cómputo estricto de riesgo, contención de errores y flujo en un grafo LangGraph compilado.

#### 2. Validación y Métricas de Calidad
- `./scripts/check.sh`: **100% verde**.
  - **Ruff:** Formateo y linter conformes en los 51 archivos del proyecto.
  - **MyPy:** Modo estricto verificado con 0 errores en 51 archivos.
  - **Pytest:** 173 pruebas pasando satisfactoriamente en 1.08s.

#### 3. Cumplimiento de Criterios de Aceptación
- [x] **Generación de ExecutionPlan:** Instancia canónica `ExecutionPlan` generada con identificador único y objetivo.
- [x] **Pasos y herramientas previstas:** Pasos ordenados con `tool_name`, argumentos y nivel de riesgo.
- [x] **Dependencias explícitas:** Campo `dependencies` poblado y validado en `PlanStep`.
- [x] **Integración limpia en AgentState:** Almacenado en `state["plan"]` para su consumo inmediato por `risk_assess` y `execute`.

/close
