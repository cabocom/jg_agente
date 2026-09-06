# Contexto del Proyecto - ISSUE-F11-T02: Implementación de InfraDiscoveryEngine y nodo observe en plugin DevOps

## 1. Identificación y Objetivos
- **Issue ID:** [jg_agente#38] [ISSUE-F11-T02]
- **Título:** Implementación de InfraDiscoveryEngine y nodo observe en plugin DevOps
- **Fase:** FASE 11 (Plugin DevOps y Observabilidad de Infraestructura)
- **Dependencias:** ISSUE-F06-T01 (Nodo observe desacoplado), ISSUE-F11-T01 (Estructura y modelos de snapshot)
- **Objetivo Principal:** Desarrollar el motor de descubrimiento y telemetría de infraestructura (`InfraDiscoveryEngine`) que recolecte estado de Host y Docker/Kubernetes, se registre como `ObserverEngine` en el `CapabilityRegistry` y deposite un diccionario serializable en `environment_snapshot` dentro de `AgentState` durante la ejecución del nodo `observe` en LangGraph.

## 2. Decisiones Arquitectónicas y Restricciones
- **Contrato Canónico `ObserverEngine`:**
  - `InfraDiscoveryEngine` extiende `ObserverEngine` (`engine_type="observer"`) y expone `async def observe(self, state: AgentState | None = None) -> dict[str, Any]`.
  - Es consumido de forma polimórfica por `app/nodes/observe.py` sin que el Core conozca los modelos de infraestructura.
- **Portabilidad y Fallback sin Dependencias Forzadas:**
  - El motor soporta recolección avanzada vía `psutil` y `docker` SDK si están instalados.
  - Implementa fallback completo nativo usando la biblioteca estándar (`platform`, `os`, `shutil`, `socket`) y sistemas de archivos virtuales de Linux (`/proc/uptime`, `/proc/meminfo`, `/proc/stat`), garantizando operatividad total en imágenes Docker mínimas y entornos CI/CD sin demonio Docker activo.
- **Detección Automática de Incidentes:**
  - El motor evalúa umbrales críticos (CPU >= 90%, Memoria >= 90%, Disco >= 90%, Contenedores unhealthy o detenidos de forma anómala) e instancia objetos `InfraIncident` dentro del snapshot consolidado.
- **Serialización en `environment_snapshot`:**
  - `InfraSnapshot.model_dump(mode="json")` retorna un diccionario nativo JSON-serializable que LangGraph almacena en `AgentState["environment_snapshot"]`, disponible para nodos posteriores (`reason`, `plan`, `execute`, `conclude`).
- **Tests Autónomos:**
  - 7 pruebas unitarias e integración en `plugins/jg_plugin_devops/tests/test_discovery.py`, probando contratos, recolección, resiliencia ante sockets faltantes, heurísticas de incidentes y ejecución contra el nodo `observe_node` de LangGraph.
