# Análisis Técnico - ISSUE-F11-T02: Implementación de InfraDiscoveryEngine y nodo observe en plugin DevOps

## 1. Alcance y Contexto Técnico
En la arquitectura agnóstica de `jg_agente`, el Core cuenta con un nodo condicional `observe` que sólo se activa si existe un `ObserverEngine` registrado en el `CapabilityRegistry` (implementado en `ISSUE-F06-T01`).
La presente tarea implementa dicho motor dentro del plugin DevOps (`jg_plugin_devops`), transformándolo en una fuente activa de telemetría de infraestructura que alimenta el flujo de toma de decisiones del agente.

## 2. Componentes Afectados y Diseñados

### 2.1. Motor de Descubrimiento (`discovery.py`)
- Clase `InfraDiscoveryEngine(ObserverEngine)`:
  - `name`: `"infra_discovery"`.
  - `engine_type`: `"observer"`.
  - `observe(state)`:
    - Recolecta `HostSnapshot` (SO, CPU, Memoria, Disco, Procesos, Servicios, Puertos).
    - Recolecta `DockerSnapshot` (Contenedores, Imágenes, Redes, Volúmenes).
    - Recolecta `KubernetesSnapshot` (Detección in-cluster o kubeconfig).
    - Evalúa `_detect_incidents` para generar `list[InfraIncident]`.
    - Genera proyecciones de métricas (`host_metrics`), estados rápidos (`containers`, `services`) y topología básica (`topology`).
    - Empaqueta todo en `InfraSnapshot` y retorna `snapshot.model_dump(mode="json")`.

### 2.2. Integración en `DevOpsPlugin` (`plugin.py`)
- `register_engines()` retorna `{"infra_discovery": self._discovery_engine}`.
- Métodos de ciclo de vida (`startup`, `shutdown`) propagados hacia `InfraDiscoveryEngine`.
- `health_check()` incluye el estado del motor (`"engine": "started" | "idle"`).

### 2.3. Batería de Pruebas (`tests/test_discovery.py`)
- `test_engine_contract_and_metadata`: valida contrato y rol `ObserverEngine`.
- `test_engine_lifecycle`: valida hooks asíncronos de inicio y apagado.
- `test_observe_telemetry_collection_and_serialization`: valida que el output es un dict serializable y deserializable con `InfraSnapshot`.
- `test_docker_fallback_when_socket_missing`: resiliencia ante socket faltante.
- `test_incident_detection_heuristics`: detección de incidentes ante CPU, RAM, disco o contenedores fallidos.
- `test_integration_with_observe_node_in_langgraph`: integración directa con `observe_node(state, registry)` verificando mutación de `environment_snapshot` y auditoría inmutable.
- `test_docker_sdk_parsing_mocked`: prueba de mapeo de atributos con mocks del SDK de Docker.

## 3. Riesgos y Mitigaciones
- **Ausencia de librerías de sistema en contenedores:**
  - *Riesgo:* En la imagen Docker ligera (`python:3.12-slim`), `psutil` o `docker` SDK no están preinstalados.
  - *Mitigación:* Implementación de fallbacks basados en la biblioteca estándar y `/proc`, comprobados en vivo en el contenedor `jg_agente` con éxito.
- **Acceso a Docker Socket denegado o no montado:**
  - *Riesgo:* Excepción `FileNotFoundError` o `PermissionError`.
  - *Mitigación:* Captura completa de excepciones devolviendo `DockerSnapshot(is_available=False, error_message=...)` sin romper la ejecución del agente.
