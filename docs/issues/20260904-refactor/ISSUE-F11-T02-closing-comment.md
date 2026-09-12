Se ha completado la implementación de **[ISSUE-F11-T02] Implementación de InfraDiscoveryEngine y nodo observe en plugin DevOps** en `jg_agente`.

### Resumen de Cambios:
1. **Módulo `discovery.py` en `jg_plugin_devops`:**
   - Implementado `InfraDiscoveryEngine` heredando de `ObserverEngine` (`engine_type="observer"`).
   - Recolección de telemetría de Host (`HostSnapshot`), Docker (`DockerSnapshot`), Kubernetes (`KubernetesSnapshot`) e Incidentes (`InfraIncident`).
   - Implementado soporte dual y portátil: utiliza `psutil` y `docker` SDK si están presentes, con fallback nativo completo (stdlib `platform`, `shutil`, `os`, `socket` y `/proc` en Linux).
   - Detección de incidentes por saturación de recursos (CPU, memoria, disco >= 90%) o anomalías en contenedores (unhealthy, exited).
   - Retorno estructurado de `InfraSnapshot.model_dump(mode="json")`.
2. **Integración con `DevOpsPlugin`:**
   - Registrado en `register_engines()` bajo la clave `"infra_discovery"`.
   - Propagación de ciclo de vida (`startup`, `shutdown`) e inclusión en `health_check()`.
3. **Tests Unitarios y de Integración:**
   - Creado `plugins/jg_plugin_devops/tests/test_discovery.py` con 7 casos de prueba cubriendo contratos, ciclo de vida, serialización, degradación sin socket, detección de incidentes e integración de extremo a extremo con `observe_node` de LangGraph.
4. **Calidad y Verificación:**
   - 20/20 tests en `plugins/jg_plugin_devops/tests/` pasando con éxito.
   - Suite completa de 286 tests pasando al 100% con Ruff y MyPy en modo estricto (`./scripts/check.sh`).
   - Verificado en el contenedor en vivo `jg_agente`: boot con `1 engines`, endpoint `/capabilities` reportando `has_observer: true` y ejecución de prueba en `POST /executions/trigger` confirmando el poblado exitoso de `environment_snapshot`.
5. **Documentación:**
   - Generado el cuarteto documental en `docs/issues/ISSUE-F11-T02-*` y actualizado el roadmap en `README.md`.
