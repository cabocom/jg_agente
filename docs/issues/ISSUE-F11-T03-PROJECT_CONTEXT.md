# Contexto del Proyecto - ISSUE-F11-T03: Implementación de DAGPlannerEngine y VerifierEngine en plugin DevOps

## 1. Identificación y Objetivos
- **Issue ID:** [jg_agente#39] [ISSUE-F11-T03]
- **Título:** Implementación de DAGPlannerEngine y VerifierEngine en plugin DevOps
- **Fase:** FASE 11 (Plugin DevOps y Observabilidad de Infraestructura)
- **Dependencias:** ISSUE-F06-T02 (Nodo plan estructurado), ISSUE-F06-T05 (Nodos verify y rollback), ISSUE-F11-T01 (Estructura y modelos de snapshot)
- **Objetivo Principal:** Desarrollar el planificador determinista/heurístico en grafo acíclico dirigido (`DAGPlannerEngine`) y el verificador post-acción (`DevopsVerifierEngine`) en `jg_plugin_devops`, registrándolos como `PlannerEngine` y `VerifierEngine` en el `CapabilityRegistry`, cumpliendo los criterios de formulación de planes con niveles de riesgo correctos y comprobación activa de resolución de problemas de servicio.

## 2. Decisiones Arquitectónicas y Restricciones
- **Planificador DAG (`DAGPlannerEngine`):**
  - Implementa el contrato `PlannerEngine` (`engine_type="planner"`).
  - Formula `ExecutionPlan` compuesto por `PlanStep`s con orden topológico y resolución de dependencias (`dependencies: list[str]`).
  - Heurística de incidentes: cuando `environment_snapshot` contiene incidentes activos, estructura un plan de remediación en 3 etapas:
    1. Diagnóstico (`RiskLevel.LOW`, sin dependencias)
    2. Remediación / Mutación (`RiskLevel.HIGH` o `MEDIUM`, reversible, dependiente de la etapa 1)
    3. Verificación (`RiskLevel.LOW`, dependiente de la etapa 2)
  - Heurística de intención/prompt: clasifica acciones destructivas (`CRITICAL`), mutaciones operativas (`HIGH`), ajustes de configuración (`MEDIUM`) y consultas (`LOW`).
  - Computa `estimated_risk` consolidado para activación condicional de HITL en el nodo `risk_assess`.
- **Verificador DevOps (`DevopsVerifierEngine`):**
  - Implementa el contrato `VerifierEngine` (`engine_type="verifier"`).
  - Inspecciona `execution_records` y `errors`:
    - Si algún paso falló o hubo errores fatales: reporta `VerificationStatus.FAIL` y `resolved=False`.
    - Si hubo advertencias no fatales: reporta `VerificationStatus.DEGRADED` y `resolved=False`.
    - Si todos los pasos se completaron exitosamente: reporta `VerificationStatus.PASS`, `resolved=True`, con checks de integridad y salud de servicio.
- **Tríada Cognitiva Completa:**
  - `DevOpsPlugin` registra simultáneamente `infra_discovery` (`observer`), `dag_planner` (`planner`) y `devops_verifier` (`verifier`) sin conflictos en `CapabilityRegistry`.
- **Tests Autónomos:**
  - 12 pruebas unitarias e integración en `plugins/jg_plugin_devops/tests/test_planner.py` y `test_verifier.py`, con cobertura de contratos, dependencias DAG, clasificación de riesgos e integración directa con `plan_node` y `verify_node` de LangGraph.
