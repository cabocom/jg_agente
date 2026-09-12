# Contexto del Proyecto — ISSUE-F06-T02

## 1. Hito Alcanzado
Implementación del nodo opcional `plan` para el ciclo cognitivo de `jg_agente` (FASE 06: Nodos Opcionales y Motores Cognitivos).

## 2. Decisiones Técnicas Clave
- **Ampliación del contrato `PlanStep`:** Se incorpora el campo `dependencies: list[str] = Field(default_factory=list)` para permitir dependencias explícitas entre pasos sin romper compatibilidad.
- **Invocación polimórfica:** Soporte para métodos `create_plan`, `plan`, `build_plan` y `generate_plan`, admitiendo tanto retornos de tipo `ExecutionPlan` como diccionarios o listas de pasos.
- **Cálculo de riesgo dinámico:** El plan calcula automáticamente el `estimated_risk` como el riesgo máximo de sus pasos para su consumo por `risk_assess` y evaluación HITL.
- **Tolerancia a fallos:** Las excepciones no controladas se transforman en `ExecutionError(fatal=False)`, generando un plan seguro para no truncar la ejecución del agente.

## 3. Estado de la Base de Código
- **Versión del Proyecto:** 2.15.0
- **Total de pruebas automatizadas:** 173 tests unitarios e integrados (100% verde).
- **Cobertura de Tipos MyPy:** 51 archivos verificados en modo estricto.
- **Calidad de Código Ruff:** 0 advertencias o errores de formato/linter en 51 archivos.
