Se ha completado la implementación de **[ISSUE-F11-T01] Estructura del paquete jg_plugin_devops y modelos de snapshot** en `jg_agente`.

### Resumen de Cambios:
1. **Paquete `plugins/jg_plugin_devops`:**
   - Estructurado como paquete independiente con su propio `pyproject.toml` declarando el punto de entrada canónico `jg_agente.plugins` (`DevOpsPlugin`).
   - Implementada la clase `DevOpsPlugin` cumpliendo rigurosamente con `BasePlugin` (metadatos, hooks de ciclo de vida `startup`/`shutdown`, `health_check` y `register_models`).
2. **Modelos de Dominio Pydantic v2 de Infraestructura:**
   - Creado `models/snapshot.py` con tipado estricto para subsistemas de Host (`HostSnapshot`, `OSInfo`, `CPUInfo`, `MemoryInfo`, `DiskPartitionInfo`, `ProcessInfo`, `ServiceInfo`, `PortInfo`), Docker (`DockerSnapshot`, `ContainerInfo`, `ImageInfo`, `NetworkInfo`, `VolumeInfo`), Kubernetes (`KubernetesSnapshot`, `PodInfo`, `DeploymentInfo`, `K8sServiceInfo`, `IngressInfo`, `K8sEventInfo`), Incidentes (`InfraIncident`, `IncidentSeverity`) y el agregador maestro `InfraSnapshot`.
3. **Persistencia ORM SQLAlchemy con Prefijo `devops_`:**
   - Creado `models/db.py` definiendo `DevopsSnapshot` (`devops_snapshots`) y `DevopsIncident` (`devops_incidents`) con convención de nombres estricta (`devops_pk_`, `devops_fk_`, `devops_ix_`, etc.) y clave foránea relacionada, garantizando aislamiento total frente a las tablas del Core (`core_*`).
4. **Batería de Pruebas Unitarias Propias:**
   - Creados 3 archivos de test en `plugins/jg_plugin_devops/tests/`:
     - `test_plugin.py`: contratos de `BasePlugin`, ciclo de vida, autodescubrimiento con `PluginManager` y verificación AST de no dependencia del Core hacia el plugin.
     - `test_snapshot_models.py`: serialización y deserialización de modelos Pydantic.
     - `test_db_models.py`: pruebas asíncronas de base de datos en memoria SQLite.
5. **Calidad y Verificación:**
   - 13/13 tests del plugin superados.
   - Suite completa de 279 tests pasando al 100% con Ruff y MyPy estricto sin errores (`./scripts/check.sh`).
   - Verificado en el contenedor vivo `jg_agente`: autodescubrimiento e inicialización limpia de `DevOpsPlugin` en paralelo con `ConversationalPlugin`.
6. **Documentación:**
   - Generado el cuarteto documental en `docs/issues/ISSUE-F11-T01-*` y actualizado el plan del proyecto en `README.md`.
