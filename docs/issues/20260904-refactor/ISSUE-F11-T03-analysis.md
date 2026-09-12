# Análisis Técnico - ISSUE-F11-T03: Implementación de DAGPlannerEngine y VerifierEngine en plugin DevOps

## 1. Alcance y Contexto Técnico
En la arquitectura del Execution Plane de `jg_agente`, los nodos `plan` y `verify` se activan dinámicamente cuando el registro de capacidades expone un `PlannerEngine` y un `VerifierEngine` respectivamente.
Esta tarea implementa ambos motores dentro del plugin `jg_plugin_devops`, permitiendo al agente formular planes acíclicos estructurados con niveles de riesgo bien delimitados y comprobar de forma activa la resolución efectiva de las operaciones de infraestructura ejecutadas.

## 2. Componentes Afectados y Diseñados

### 2.1. Planificador DAG (`planner.py`)
- Clase `DAGPlannerEngine(PlannerEngine)`:
  - `name`: `"dag_planner"`.
  - `engine_type`: `"planner"`.
  - `create_plan(state)` / `plan(state)`:
    - Extracción de objetivo (`goal`) y texto de contexto.
    - Heurística 1 (Incident-driven): si hay anomalías en `environment_snapshot`, descompone cada incidente en un sub-DAG de 3 pasos (diagnóstico -> remediación -> verificación) con orden topológico estricto.
    - Heurística 2 (Prompt-driven): categoriza riesgos:
      - Destructivo (`eliminar`, `destruir`, `prune`) -> `RiskLevel.CRITICAL`.
      - Mutación (`reiniciar`, `restart`, `deploy`) -> `RiskLevel.HIGH` (reversible).
      - Recarga/Limpieza (`reload`, `clear`) -> `RiskLevel.MEDIUM`.
      - Auditoría/Lectura -> `RiskLevel.LOW`.
    - Computa `estimated_risk = _compute_highest_risk(steps)` para que el nodo posterior `risk_assess` active HITL cuando sea necesario.

### 2.2. Verificador de Operaciones (`verifier.py`)
- Clase `DevopsVerifierEngine(VerifierEngine)`:
  - `name`: `"devops_verifier"`.
  - `engine_type`: `"verifier"`.
  - `verify(state)` / `verify_execution(state)`:
    - Inspecciona `state["execution_records"]` (instancias de `StepExecutionRecord`):
      - Si algún registro tiene `status == StepStatus.FAILED`: reporta `VerificationStatus.FAIL` y `resolved=False`.
    - Inspecciona `state["errors"]` (instancias de `ExecutionError`):
      - Si hay errores con `fatal=True`: reporta `VerificationStatus.FAIL` y `resolved=False`.
      - Si hay errores no fatales: reporta `VerificationStatus.DEGRADED`.
    - Si no hay fallos: determina el servicio objetivo a partir del plan y certifica `VerificationStatus.PASS`, `resolved=True`, con checks estructurados de integridad y salud.

### 2.3. Integración en `DevOpsPlugin` (`plugin.py`)
- `register_engines()` expone la tríada completa:
  - `"infra_discovery"`: `InfraDiscoveryEngine` (`observer`)
  - `"dag_planner"`: `DAGPlannerEngine` (`planner`)
  - `"devops_verifier"`: `DevopsVerifierEngine` (`verifier`)
- Métodos de ciclo de vida (`startup`, `shutdown`) propagados a todos los motores.
- `health_check()` reporta el estado individual de cada motor en `"engines"`.

### 2.4. Batería de Pruebas
- `tests/test_planner.py` (5 tests): contratos, ciclo de vida, dependencias DAG ante incidentes, categorización de riesgos por prompt e integración directa con `plan_node`.
- `tests/test_verifier.py` (7 tests): contratos, ciclo de vida, resolución exitosa, fallos en pasos, errores fatales, estado degradado e integración directa con `verify_node`.
- `tests/test_plugin.py`: validación de los 3 motores registrados en `DevOpsPlugin`.

## 3. Riesgos y Mitigaciones
- **Conflictos en `CapabilityRegistry`:**
  - *Riesgo:* `BootConflictError` al registrar múltiples motores.
  - *Mitigación:* Cada motor posee un `engine_type` distinto (`observer`, `planner`, `verifier`), cumpliendo la política de singletons funcionales del Core.
- **Ciclos en el grafo de pasos:**
  - *Riesgo:* Dependencias circulares que bloqueen la ejecución secuencial.
  - *Mitigación:* La formulación garantiza que cada paso sólo puede depender de identificadores asignados con anterioridad cronológica (`step_ids.index(dep) < step_ids.index(current)`).
