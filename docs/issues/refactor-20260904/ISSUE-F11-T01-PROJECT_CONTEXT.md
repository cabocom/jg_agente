# Contexto del Proyecto - ISSUE-F11-T01: Estructura del paquete jg_plugin_devops y modelos de snapshot

## 1. Identificación y Objetivos
- **Issue ID:** [jg_agente#37] [ISSUE-F11-T01]
- **Título:** Estructura del paquete jg_plugin_devops y modelos de snapshot
- **Fase:** FASE 11 (Plugin DevOps y Observabilidad de Infraestructura)
- **Dependencias:** ISSUE-F04-T01 (Sistema de Plugins y CapabilityRegistry)
- **Objetivo Principal:** Crear el paquete del plugin DevOps (`jg_plugin_devops`) con modelos Pydantic v2 de infraestructura (`InfraSnapshot`, `HostSnapshot`, `DockerSnapshot`, `KubernetesSnapshot`, `InfraIncident`), tablas de persistencia ORM con prefijo `devops_` (`devops_snapshots`, `devops_incidents`) y cumplimiento estricto del contrato `BasePlugin` sin alterar el Core de `jg_agente`.

## 2. Decisiones Arquitectónicas y Restricciones
- **Aislamiento Radical del Core (SEC-06 & Agnosticismo):**
  - El Core del agente (`app/`) permanece 100% genérico y agnóstico de infraestructura.
  - Ninguna entidad del Core importa o conoce la existencia de `InfraSnapshot` o conceptos de Docker/Kubernetes.
- **Modelado Pydantic v2 Fuertemente Tipado:**
  - `HostSnapshot`: telemetría de hardware y sistema operativo (`OSInfo`, `CPUInfo`, `MemoryInfo`, `DiskPartitionInfo`, `ProcessInfo`, `ServiceInfo`, `PortInfo`).
  - `DockerSnapshot`: estado de contenedores, imágenes, redes y volúmenes (`ContainerInfo`, `ContainerPortInfo`, `ImageInfo`, `NetworkInfo`, `VolumeInfo`).
  - `KubernetesSnapshot`: recursos de clúster (`PodInfo`, `DeploymentInfo`, `K8sServiceInfo`, `IngressInfo`, `K8sEventInfo`).
  - `InfraIncident`: anomalías detectadas con severidades normalizadas (`IncidentSeverity`: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`).
  - `InfraSnapshot`: contenedor maestro consolidado con proyecciones y metadatos.
- **Persistencia ORM con Prefijo `devops_`:**
  - Tablas dedicadas: `devops_snapshots` y `devops_incidents`.
  - Convención de nombres estricta (`devops_pk_`, `devops_fk_`, `devops_ix_`, `devops_uq_`, `devops_ck_`), completamente diferenciada de `core_*`.
  - Filtro en Alembic del Core garantizando que las migraciones del Core no interfieran con tablas del plugin.
- **Ciclo de Vida y Autodescubrimiento:**
  - `DevOpsPlugin` hereda de `BasePlugin`, implementando `get_plugin_metadata`, `register_tools`, `register_engines`, `register_models`, `startup`, `shutdown` y `health_check`.
  - Autodescubierto dinámicamente por `PluginManager` conviviendo armónicamente con `ConversationalPlugin`.
- **Localización de Tests:**
  - Tests autónomos en `plugins/jg_plugin_devops/tests/` ejecutables tanto de forma independiente como integrados en `./scripts/check.sh`.
