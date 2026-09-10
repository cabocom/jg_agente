# Análisis Técnico: ISSUE-F05-T03 — Implementación de nodo base: execute

> **Issue ID:** `ISSUE-F05-T03`  
> **Fase:** `FASE 05`  
> **Componente:** `jg_agente.nodes.execute`  
> **Fecha:** 5 de septiembre de 2026  
> **Prioridad:** Critical | **Complejidad:** M  
> **Dependencias:** `ISSUE-F03-T05` (SecurityGuard); `ISSUE-F05-T01` (GraphBuilder)

---

## 1. Contexto y Objetivos

El nodo `execute` es el actuador operacional central en la arquitectura LangGraph de `jg_agente`. Es el encargado de procesar y ejecutar secuencialmente las herramientas autorizadas requeridas para cumplir los objetivos del agente, provengan de un plan estructurado (`ExecutionPlan`) formulado por un `PlannerEngine` o de llamadas reactivas a herramientas (`tool_calls`) emitidas directamente por el modelo de lenguaje en el nodo `reason`.

---

## 2. Requisitos y Criterios de Aceptación

- **Criterio de Aceptación:** `Nodo execute ejecuta herramientas autorizadas secuencialmente, captura fallos y guarda rollback_context en el estado.`
- **Ejecución Sandboxed:** Toda invocación física de herramientas debe pasar por el interceptor `SecurityGuard.execute_tool()`, validando permisos requeridos, niveles de riesgo, inyecciones de comandos y políticas SSRF.
- **Métricas Temporales:** Recolectar la duración precisa en milisegundos (`duration_ms`) de cada herramienta ejecutada.
- **Tolerancia y Contención de Fallos:** Capturar excepciones y fallos operacionales emitiendo registros estructurados `ExecutionError` y deteniendo de forma controlada los pasos subsiguientes de la secuencia para evitar inconsistencias en cascada.
- **Preservación de Compensación (`rollback_context`):** Capturar y almacenar rigurosamente en cada `StepExecutionRecord` los datos de estado devueltos por herramientas reversibles para su uso posterior por el nodo `rollback`.
- **Integración con Memoria Conversacional (`ToolMessage`):** Cuando la ejecución proceda de llamadas de herramientas emitidas por el LLM, generar mensajes `ToolMessage` correspondientes a cada `tool_call_id`.
- **Auditoría Inmutable:** Emitir registros `AuditRecord` bajo el evento `execute_completed` con detalles de herramientas ejecutadas, éxitos y fallos.

---

## 3. Decisiones de Diseño

1. **Resolución Polimórfica de Tareas a Ejecutar:**
   - Prioridad 1: `ExecutionPlan` (`state["plan"]`), procesando sus `steps: list[PlanStep]`.
   - Prioridad 2: `tool_calls` en `IntentModel.parameters` o `state["intent"]`.
   - Prioridad 3: Herramienta base disponible en `CapabilityRegistry` (fallback para pruebas y topologías mínimas).

2. **Gobernanza Human-In-The-Loop (HITL):**
   - El nodo inspecciona `state["approval"]`. Si el estado es `ApprovalStatus.APPROVED`, se habilita `bypass_approval=True` para autorizar operaciones clasificadas como `RiskLevel.HIGH` o `CRITICAL`.
   - Si no existe aprobación y la herramienta la requiere, `SecurityGuard` deniega la ejecución física y el paso se marca como `FAILED` con el motivo correspondiente.

3. **Soporte Asíncrono Transparente:**
   - Soporte para herramientas cuya función ejecutable devuelva corrutinas (`async def`), asegurando la resolución asíncrona mediante `await`.
