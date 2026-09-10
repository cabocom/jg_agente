# Análisis Técnico - ISSUE-F11-T01: Estructura del paquete jg_plugin_devops y modelos de snapshot

## 1. Alcance y Contexto Técnico
La fase FASE 11 introduce las capacidades SRE y de observabilidad de infraestructura en `jg_agente`. Para cumplir con el principio de agnosticismo de dominio, el Core no debe albergar conceptos de servidores, métricas de CPU/RAM, contenedores Docker ni recursos de Kubernetes.
Esta tarea sienta la base fundacional del plugin `jg_plugin_devops`:
- Estructura de paquete independiente `plugins/jg_plugin_devops`.
- Modelos de dominio Pydantic v2 para telemetría y captura integral de infraestructura (`InfraSnapshot`).
- Modelos de persistencia ORM SQLAlchemy con prefijo obligatorio `devops_`.
- Implementación de la clase `DevOpsPlugin(BasePlugin)` para integración transparente en `PluginManager`.

## 2. Componentes Afectados y Diseñados

### 2.1. Paquete `plugins/jg_plugin_devops`
- `pyproject.toml`: Metadatos del paquete y punto de entrada:
  `[project.entry-points."jg_agente.plugins"] devops = "jg_plugin_devops.plugin:DevOpsPlugin"`.
- `plugin.py`: Clase `DevOpsPlugin` cumpliendo `BasePlugin`:
  - Metadatos: `name="devops"`, `version="0.1.0"`, tags de SRE/infraestructura.
  - Métodos de ciclo de vida (`startup`, `shutdown`, `health_check`).
  - Registro de modelos Pydantic (`register_models`).
- `models/snapshot.py`:
  - Enums: `IncidentSeverity` (`StrEnum`).
  - Modelos Host: `OSInfo`, `CPUInfo`, `MemoryInfo`, `DiskPartitionInfo`, `ProcessInfo`, `ServiceInfo`, `PortInfo`, `HostSnapshot`.
  - Modelos Docker: `ContainerPortInfo`, `ContainerInfo`, `ImageInfo`, `NetworkInfo`, `VolumeInfo`, `DockerSnapshot`.
  - Modelos Kubernetes: `PodInfo`, `DeploymentInfo`, `K8sServiceInfo`, `IngressInfo`, `K8sEventInfo`, `KubernetesSnapshot`.
  - Modelo Incidente: `InfraIncident` con timestamp UTC, severidad y atributos de resolución.
  - Modelo Raíz: `InfraSnapshot` que consolida todos los anteriores junto a proyecciones rápidas (`host_metrics`, `containers`, `services`, `topology`).
- `models/db.py`:
  - `devops_metadata` con convención de nombres `devops_*`.
  - `DevopsSnapshot` mapeado a `devops_snapshots`.
  - `DevopsIncident` mapeado a `devops_incidents` con clave foránea a `devops_snapshots.id`.

### 2.2. Aislamiento y Configuración Raíz
- `pyproject.toml`: Inclusión de `jg_plugin_devops` en `known-first-party` (isort) y `pythonpath` (pytest).
- `tests/`: Batería de tests propia en `plugins/jg_plugin_devops/tests/` cubriendo contratos, modelos Pydantic, y CRUD asíncrono con base de datos SQLite en memoria.

## 3. Riesgos y Estrategias de Mitigación
- **Riesgo:** Acoplamiento inadvertido del Core hacia el plugin DevOps.
  - *Mitigación:* Test estricto con análisis AST (`test_strict_core_isolation`) que verifica que ningún archivo dentro de `app/` importe `jg_plugin_devops`.
- **Riesgo:** Colisión de esquemas o migraciones en la base de datos con tablas del Core.
  - *Mitigación:* Prefijo forzoso `devops_` en metadatos y exclusión explícita en el filtro de Alembic del Core (`include_object` filtra únicamente `core_*`).
