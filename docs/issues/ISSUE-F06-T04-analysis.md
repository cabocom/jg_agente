# Análisis Técnico — ISSUE-F06-T04

## 1. Identificación y Metadatos
- **Issue ID:** `ISSUE-F06-T04`
- **Título:** Implementación de nodo de pausa HITL y reanudación (human_approval)
- **Fase:** FASE 06 (Nodos Opcionales y Motores Cognitivos)
- **Prioridad:** Critical
- **Complejidad Estimada:** L
- **Dependencias:** `ISSUE-F03-T02`; `ISSUE-F06-T03`
- **Criterios de Aceptación:**
  - Grafo pausa ejecución en checkpoint persistente al entrar en `human_approval` y queda en espera sin bloquear el proceso.

---

## 2. Contexto y Objetivos Técnicos
En la arquitectura de ejecución distribuida y resiliente de `jg_agente`, el patrón Human-In-The-Loop (HITL) requiere suspender con seguridad cualquier acción clasificada con `RiskLevel >= HIGH` o `CRITICAL`. La suspensión debe ser no bloqueante para los hilos del proceso (asíncrona) y respaldada de manera duradera en el checkpointer (PostgreSQL o MemorySaver).

El nodo `human_approval`:
1. Se sitúa tras la bifurcación condicional de `risk_assess` cuando `requires_approval=True` (`risk_assess -> human_approval`).
2. Utiliza la primitiva nativa `langgraph.types.interrupt(interrupt_payload)` para generar un snapshot persistente del estado y suspender el grafo sin acaparar recursos de CPU ni bloquear el event loop.
3. Expone en el payload de interrupción toda la metadata necesaria para la UI o el Dashboard de administración (`action`, `execution_id`, `thread_id`, `risk_assessment`, `plan`, `message`).
4. Reanuda la ejecución cuando un operador humano interactúa mediante `Command(resume=payload)` suministrando un veredicto estructurado (`ApprovalRecord`, diccionario con flags `approved`, o booleano directo).
5. Si la decisión es de aprobación (`status=APPROVED`), actualiza `status=AgentExecutionStatus.EXECUTING`, limpia las banderas de intervención requerida (`requires_approval=False`, `human_intervention_required=False`), genera auditoría `human_approval_completed` y enruta hacia `execute`.
6. Si la decisión es de rechazo (`status=REJECTED`), marca `status=AgentExecutionStatus.FAILED`, genera auditoría `human_approval_rejected` y enruta hacia `conclude` para devolver la respuesta controlada al usuario.
7. Si el estado ya cuenta con una decisión previa (`APPROVED` o `REJECTED`), actúa en modo pass-through sin invocar `interrupt()` de forma redundante.
8. Si se invoca fuera del contexto runnable de LangGraph (en invocaciones directas unitarias offline), captura `RuntimeError` limpiamente y devuelve el estado `AWAITING_APPROVAL` con auditoría sin colapsar el proceso.

---

## 3. Decisiones de Diseño y Arquitectura
- **Interrupción Nativa de LangGraph (`interrupt()`):** Se descartan mecanismos de espera activa (`polling`, `asyncio.sleep`) a favor del modelo checkpoint-resume de LangGraph. Al invocar `interrupt()`, LangGraph levanta internamente una excepción de control (`GraphInterrupt`), serializa el estado en el checkpointer y retorna el control a la invocación del cliente.
- **Reanudación Desacoplada con `Command(resume=...)`:** Los operadores externos (Dashboard Web, CLI, API REST) pueden autorizar o denegar una operación en cualquier momento posterior reutilizando el mismo `thread_id`, sin necesidad de mantener conexiones abiertas o sockets bloqueantes.
- **Polimorfismo en Cargas de Reanudación:** Soporta payloads flexibles (`ApprovalRecord`, `{"approved": bool, "approver": str, "notes": str}`, `bool`) asegurando compatibilidad con diferentes orígenes de cliente.
- **Trazabilidad Inmutable:** Cada transición HITL queda registrada en `state["audit_trail"]` con su actor responsable, justificación y tiempo de ciclo (`duration_ms`).

---

## 4. Plan de Pruebas
1. Invocación offline directa fuera de contexto runnable capturando `RuntimeError`.
2. Pase transparente ante estado previamente aprobado (`ApprovalStatus.APPROVED`).
3. Pase transparente ante estado previamente rechazado (`ApprovalStatus.REJECTED`).
4. Validación de bifurcación determinista en `route_after_human_approval`.
5. Integración completa de grafo LangGraph con `MemorySaver`:
   - Detección de suspensión en checkpoint (`__interrupt__`, `aget_state()`).
   - Reanudación con aprobación (`Command(resume=...)`) concluyendo satisfactoriamente (`RESOLVED`, herramienta ejecutada).
   - Reanudación con rechazo (`Command(resume=...)`) finalizando con fallo controlado (`FAILED`, herramienta omitida).
