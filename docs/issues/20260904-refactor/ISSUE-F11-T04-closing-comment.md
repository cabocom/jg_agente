Se ha completado la implementación de **[ISSUE-F11-T04] Implementación de herramientas Docker con rollback_func en plugin DevOps** en `jg_agente`.

### Resumen de Cambios:
1. **Herramienta `DockerRestartTool` (`plugins/jg_plugin_devops/docker_tools.py`):**
   - Implementado el esquema Pydantic `DockerRestartArgs` con validación regex estricta contra inyección de comandos o caracteres maliciosos.
   - Implementada la función de ejecución `restart_container_fn` capturando el estado previo del contenedor (`running`, `exited`, `paused`) en `rollback_context`.
   - Implementada la función de compensación `rollback_restart_container_fn`, capaz de restaurar el estado original del contenedor (`stop` si estaba parado/caído, `pause` si estaba pausado, o verificación si estaba corriendo).
   - Instanciada la herramienta canónica `DockerRestartTool` con `risk_level=RiskLevel.HIGH`, `reversible=True`, `read_only=False`, `tool_type=ToolType.ACTUATOR` y `rollback_func` de compensación registrado.
   - Soporte para modo de simulación determinista (`DOCKER_SIMULATION_MODE=true`) para entornos de desarrollo y CI/CD sin daemon Docker.

2. **Integración con el Plugin y el Planificador:**
   - Registrada la herramienta en `DevOpsPlugin.register_tools()`, reflejándose automáticamente en el catálogo de capacidades del agente (`GET /capabilities`).
   - Sincronizado `DAGPlannerEngine` para asignar `docker_restart` en las propuestas de remediación de contenedores en `_plan_from_incidents`.
   - Exportados `DockerRestartTool`, `DockerRestartArgs` y `create_docker_restart_tool` en `jg_plugin_devops/__init__.py`.

3. **Verificación y Pruebas:**
   - Creada suite de pruebas en `plugins/jg_plugin_devops/tests/test_docker_tools.py` con 12 casos que cubren validación de esquemas, ejecución normal y con errores, modo simulado, los 3 escenarios de compensación de rollback y la integración end-to-end con `rollback_node` de LangGraph.
   - Verificación estricta superada al 100%:
     - `ruff check app tests plugins`: Sin errores.
     - `ruff format --check app tests plugins`: 96 archivos formateados correctamente.
     - `mypy app tests plugins`: 0 errores de tipado estricto en 96 archivos.
     - `pytest`: 310 tests aprobados en 37.46s (44 tests de `jg_plugin_devops`).
     - Verificación en vivo en `http://localhost:8001/capabilities` confirmando 3 herramientas registradas (`get_weather`, `get_news`, `docker_restart`), 3 motores cognitivos (`infra_discovery`, `dag_planner`, `devops_verifier`) y `has_observer=True, has_planner=True, has_verifier=True`.
   - Actualizado el estado de la **Fase 11** al 100% en `README.md`.

Con esta tarea queda completada la totalidad de los issues planificados para el agente (`jg_agente`).
