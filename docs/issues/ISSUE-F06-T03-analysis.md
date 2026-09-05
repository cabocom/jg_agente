# Análisis Técnico — ISSUE-F06-T03

## 1. Identificación y Metadatos
- **Issue ID:** `ISSUE-F06-T03`
- **Título:** Implementación de nodo de evaluación de riesgo y política HITL (risk_assess)
- **Fase:** FASE 06 (Nodos Opcionales y Motores Cognitivos)
- **Prioridad:** Critical
- **Complejidad Estimada:** M
- **Dependencias:** `ISSUE-F03-T05`; `ISSUE-F06-T02`
- **Criterios de Aceptación:**
  - Acciones con `RiskLevel >= HIGH` marcan `requires_approval=True` y enrutan la ejecución hacia el nodo `human_approval`.

---

## 2. Contexto y Objetivos Técnicos
En la arquitectura del ciclo cognitivo de `jg_agente`, el principio "Security by Design" exige que ninguna herramienta de riesgo elevado o crítico se ejecute de forma autónoma sin previa inspección de gobernanza.

El nodo `risk_assess`:
1. Se sitúa entre `plan` y `execute` (`plan -> risk_assess -> execute` o `human_approval`).
2. Se activa si el plan formulado contiene mutaciones o herramientas declaradas.
3. Evalúa cada acción mediante `SecurityGuard` (reutilizando la infraestructura de validación de permisos, protección SSRF e inyección shell implementada en `ISSUE-F03-T05`).
4. Si alguna acción presenta `RiskLevel.HIGH` o `RiskLevel.CRITICAL`:
   - Marca formalmente `requires_approval = True` y `human_intervention_required = True`.
   - Modifica el estado operacional a `status = AgentExecutionStatus.AWAITING_APPROVAL`.
   - Inicializa el registro canónico `ApprovalRecord(status=ApprovalStatus.PENDING)`.
   - Enruta condicionalmente en LangGraph hacia `human_approval` para pausar la ejecución en un checkpoint hasta la autorización del operador humano.
5. Si todas las acciones son de bajo/medio riesgo y seguras, emite veredicto `ALLOW` y permite la transición directa hacia `execute`.
6. Si alguna acción incurre en violaciones severas (inyección de comandos shell, directory traversal, SSRF prohibido), emite veredicto `DENY`, activa el `circuit_breaker_active` y deriva hacia `conclude` con estado `FAILED`.

---

## 3. Decisiones de Diseño y Arquitectura
- **Extensión Canónica de `AgentState`:** Se incorporó el campo `requires_approval: bool` en el contrato canónico de estado para unificar la observabilidad de gobernanza HITL.
- **Introspección Híbrida de Acciones:** Capacidad de evaluar operaciones provenientes tanto de planes estructurados (`ExecutionPlan.steps`) como de llamadas directas reactivas (`tool_calls`).
- **Separación de Evaluación Previa y Autorización en Runtime:** Durante la evaluación de riesgo, `SecurityGuard` evalúa riesgos y directivas de inyección asumiendo los permisos necesarios del paso, derivando en `REQUIRE_HUMAN_APPROVAL` para que la autorización sea concedida por el operador sin abortos prematuros por permisos de invocación.
- **Preservación de Estado de Aprobación:** En reanudaciones tras checkpoint HITL donde `approval.status == APPROVED`, `risk_assess_node` respeta la decisión humana preexistente y no sobreescribe el estado a `PENDING`.

---

## 4. Plan de Pruebas
1. Detección de paso `RiskLevel.HIGH` marcando `requires_approval=True` y `ApprovalRecord(status=PENDING)`.
2. Detección de paso `RiskLevel.CRITICAL` activando `can_cause_data_loss=True`.
3. Plan de bajo riesgo (`RiskLevel.LOW`) auto-autorizado (`ALLOW`).
4. Evaluación de `tool_calls` directas sin plan formal.
5. Detección de inyección shell y bloqueo inmediato (`DENY`).
6. Preservación de autorizaciones previas aprobadas (`ApprovalStatus.APPROVED`).
7. Integración con grafo LangGraph compilado y suspensión en checkpoint antes de `human_approval`.
