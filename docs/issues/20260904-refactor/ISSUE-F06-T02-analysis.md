# Análisis Técnico — ISSUE-F06-T02

## 1. Identificación y Metadatos
- **Issue ID:** `ISSUE-F06-T02`
- **Título:** Implementación de nodo opcional: plan
- **Fase:** FASE 06 (Nodos Opcionales y Motores Cognitivos)
- **Prioridad:** High
- **Complejidad Estimada:** M
- **Dependencias:** `ISSUE-F05-T01`
- **Criterios de Aceptación:**
  - Nodo `plan` genera `ExecutionPlan` conteniendo pasos, herramientas previstas y dependencias; se integra limpiamente en `AgentState`.

---

## 2. Contexto y Objetivos Técnicos
En la arquitectura del ciclo cognitivo de `jg_agente`, cuando el modelo de razonamiento en `reason_node` detecta una solicitud operativa compleja y existe un `PlannerEngine` registrado en `CapabilityRegistry`, la intención se clasifica con `action_type = "plan"`.

El nodo `plan`:
1. Se sitúa tras el nodo `reason` y antes de la evaluación de riesgo (`reason -> plan -> risk_assess`).
2. Se activa dinámicamente si existe un `PlannerEngine` registrado en el catálogo.
3. Transforma la intención del agente (`state["intent"]`) o el estímulo inicial en una secuencia estructurada de pasos (`ExecutionPlan`).
4. Cada paso (`PlanStep`) define:
   - `step_id`: Identificador unívoco del paso.
   - `tool_name`: Nombre de la herramienta prevista.
   - `tool_args`: Argumentos previstos.
   - `dependencies`: Lista de `step_ids` que deben completarse previamente.
   - `risk_level`: Nivel de riesgo operacional del paso.
   - `reversible`: Indicador de compensabilidad/rollback.
5. Consolida el nivel de riesgo global del plan (`estimated_risk`) como el máximo riesgo entre todos sus pasos.
6. Permite fallback seguro si el motor de planificación no está disponible o falla, derivando en un plan predeterminado basado en herramientas disponibles.
7. Emite eventos inmutables de auditoría `planning_completed` con duración en milisegundos (`duration_ms`).

---

## 3. Decisiones de Diseño y Arquitectura
- **Modelo de Dependencias en `PlanStep`:** Se añadió formalmente el campo `dependencies: list[str] = Field(default_factory=list)` para expresar grafos de dependencias entre pasos.
- **Invocación Flexible y Polimórfica:** El nodo busca métodos candidatos (`create_plan`, `plan`, `build_plan`, `generate_plan`), aceptando ejecuciones síncronas o asíncronas y transformando retornos tipo `ExecutionPlan`, `dict` o `list[PlanStep]`.
- **Cálculo de Riesgo Dinámico:** Función de ordenamiento de riesgo (`LOW < MEDIUM < HIGH < CRITICAL`) para asegurar que el `estimated_risk` del plan refleja con veracidad cualquier paso de riesgo crítico o elevado.
- **Tolerancia a Fallos:** Captura excepciones con emisión de `ExecutionError(component="plan", fatal=False)` y genera un plan contingente seguro para no bloquear la finalización del agente.

---

## 4. Plan de Pruebas
1. Invocación asíncrona con motor (`AsyncMockPlanner`) con pasos y dependencias.
2. Invocación síncrona con motor (`SyncMockPlanner`).
3. Conversión de planes devueltos como diccionarios planos.
4. Conversión de listas de pasos retornadas por `generate_plan()`.
5. Fallback sin motor de planificación usando catálogo de herramientas.
6. Recálculo automático de `estimated_risk` al nivel más alto.
7. Contención de excepciones con emisión de `ExecutionError`.
8. Integración end-to-end dentro de un grafo LangGraph compilado (`reason -> plan -> execute -> conclude`).
