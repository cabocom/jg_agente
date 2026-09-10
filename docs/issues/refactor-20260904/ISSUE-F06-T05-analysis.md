# Análisis Técnico — ISSUE-F06-T05

## 1. Identificación y Metadatos
- **Issue ID:** `ISSUE-F06-T05`
- **Título:** Implementación de nodos verify y rollback
- **Fase:** FASE 06 (Nodos Opcionales y Motores Cognitivos)
- **Prioridad:** Critical
- **Complejidad Estimada:** L
- **Dependencias:** `ISSUE-F02-T03`; `ISSUE-F05-T03`
- **Criterios de Aceptación:**
  - Si `verify` detecta anomalía y la tool tiene `rollback_func`, se ejecuta compensación automática registrando el resultado en el estado.

---

## 2. Contexto y Objetivos Técnicos
En la arquitectura autónoma y resiliente de `jg_agente`, la verificación activa del entorno y la compensación automática ante efectos colaterales no deseados constituyen garantías fundamentales de fiabilidad.

Los nodos `verify` y `rollback`:
1. **`verify`:** Se intercala tras el nodo `execute` (`execute -> verify`).
   - Comprueba activamente el estado del entorno mediante `CapabilityRegistry.get_verifier()`.
   - Si no hay un `VerifierEngine` registrado, aplica una verificación básica determinista sobre `execution_records` y `errors`.
   - Produce un veredicto estructurado (`VerificationStatus.PASS`, `VerificationStatus.FAIL`, `VerificationStatus.DEGRADED`).
   - Registra el resultado en `state["verification_results"]` y emite auditoría inmutable (`verification_completed` o `verification_failed`).
2. **`route_after_verify`:**
   - Si la verificación fue exitosa (`PASS`), enruta hacia `conclude`.
   - Si la verificación detectó anomalía (`FAIL` o `DEGRADED`) y existen herramientas reversibles ejecutadas con `rollback_context`, enruta hacia `rollback`.
   - Si la verificación falló pero no hay herramientas reversibles, enruta directamente hacia `conclude`.
3. **`rollback`:**
   - Recorre en orden cronológico inverso (`reversed(records)`) los pasos completados (`StepStatus.COMPLETED`).
   - Para cada herramienta reversible, invoca `tool.rollback(rec.rollback_context)`.
   - Aplica política de máximo esfuerzo (best-effort): los fallos en una compensación no impiden la ejecución de las demás.
   - Registra las trazas de compensación en `state["rollback_records"]`.
   - Fija `state["status"] = AgentExecutionStatus.FAILED` y añade un `ExecutionError(code="ROLLBACK_TRIGGERED", fatal=True)`.
   - Emite auditoría inmutable `rollback_completed` con recuento de pasos y tasa de éxito.
   - Enruta incondicionalmente hacia `conclude` para devolver una respuesta resolutiva controlada al usuario.

---

## 3. Decisiones de Diseño y Arquitectura
- **Inversión de Orden en Compensación (LIFO):** El rollback se ejecuta estrictamente en orden cronológico inverso (`reversed()`), asegurando que las dependencias creadas en pasos posteriores se deshagan antes de revertir los pasos iniciales.
- **Uso Estricto de `rollback_context`:** La herramienta reversible recibe exactamente el diccionario de contexto que emitió durante su ejecución exitosa (`ToolResult.rollback_context`), garantizando que la compensación posea los IDs y estados necesarios (e.g. `resource_id`, backup snapshot).
- **Aislamiento y Resiliencia en Rollback:** Las excepciones dentro de un compensador de herramienta son capturadas y registradas con `success=False` sin abortar el rollback de los pasos restantes.
- **Reflejo en Salida Sintetizada (`conclude_node`):** `conclude_node` detecta la ocurrencia de rollback o fallos de verificación y genera un `AgentOutput` con `status=failed` y una respuesta explicativa del proceso de compensación.

---

## 4. Plan de Pruebas
1. Verificación exitosa con `VerifierEngine` marcando `PASS`.
2. Detección de anomalía con `VerifierEngine` marcando `FAIL` y registrando error.
3. Fallback de verificación autónoma sin motor registrado.
4. Resiliencia ante excepciones no controladas en el `VerifierEngine`.
5. Ejecución de rollback en orden cronológico inverso con `rollback_context`.
6. Omisión segura de herramientas no reversibles.
7. Tolerancia a fallos parciales durante el rollback.
8. Validación de bifurcación determinista en `route_after_verify`.
9. Integración completa de grafo LangGraph: `execute` -> `verify` (PASS) -> `conclude` (RESOLVED).
10. Integración completa de grafo LangGraph: `execute` -> `verify` (FAIL) -> `rollback` -> `conclude` (FAILED).
