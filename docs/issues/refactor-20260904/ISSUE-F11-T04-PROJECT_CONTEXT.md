# Contexto de Proyecto: [ISSUE-F11-T04] Implementación de herramientas Docker con rollback_func en plugin DevOps

## 1. Identificación y Estado
- **Issue ID:** ISSUE-F11-T04
- **Fase:** FASE 11 (Plugin DevOps y Observabilidad de Infraestructura)
- **Prioridad:** Critical
- **Complejidad Estimada:** M
- **Dependencias Previas:** ISSUE-F02-T03, ISSUE-F11-T01
- **Estado:** Implementado / Verificado

## 2. Alineación Arquitectónica
En el diseño canónico de `jg_agente` (Informe Arquitectónico 3, Sección 4.2), `DockerRestartTool` constituye la primera herramienta operativa con efectos colaterales de mutación (`ToolType.ACTUATOR`) y nivel de riesgo alto (`RiskLevel.HIGH`).

El sistema cognitivo exige:
1. **Evaluación de Riesgo y HITL:** Al poseer `risk_level=HIGH`, su ejecución queda sujeta a revisión en el nodo `risk_assess` y eventual aprobación humana en el nodo `human_approval`.
2. **Reversibilidad y Compensación (`reversible=True`):** Ante cualquier fallo en pasos posteriores de la cadena de ejecución o anomalía detectada por el nodo `verify`, el nodo `rollback_node` debe compensar la acción ejecutada en orden cronológico inverso.
3. **Preservación del Contexto de Reversión (`rollback_context`):** La herramienta captura con precisión el estado pre-operacional del contenedor (`"running"`, `"exited"`, `"paused"`) para que `rollback_func` restaure dicho estado específico en lugar de realizar una acción genérica.
4. **Agnosticismo del Core:** El núcleo (`app/`) no contiene dependencias de Docker ni SDKs específicos; toda la lógica vive encapsulada en `plugins/jg_plugin_devops/`.

## 3. Criterios de Aceptación
- `DockerRestartTool` ejecuta el reinicio de un contenedor Docker identificado por nombre o ID.
- `rollback_context` preserva el estado previo del contenedor (`running`, `exited`, `paused`).
- `rollback_func` es capaz de restaurar el estado anterior en caso de fallo posterior.
- 100% de cumplimiento con las validaciones de tipo estrictas de MyPy y formateo de Ruff.
