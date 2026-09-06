# Walkthrough: [ISSUE-F11-T04] Implementación de herramientas Docker con rollback_func en plugin DevOps

## 1. Resumen de la Implementación
Se ha completado satisfactoriamente la implementación de **DockerRestartTool** dentro del plugin `jg_plugin_devops`, proporcionando accionamiento seguro sobre contenedores Docker con clasificación de riesgo alto (`RiskLevel.HIGH`), reversibilidad explícita (`reversible=True`), captura contextual del estado previo y compensación funcional automatizada.

## 2. Componentes Desarrollados y Modificados

### 2.1 Módulo `plugins/jg_plugin_devops/docker_tools.py`
- **`DockerRestartArgs`:** Esquema Pydantic para validar `container` (con regex `CONTAINER_NAME_REGEX` y limpieza de barras) y `timeout` (entre 1s y 120s).
- **`restart_container_fn`:** Ejecuta el reinicio del contenedor, capturando `container_name`, `container_id` y `previous_state` en `rollback_context`.
- **`rollback_restart_container_fn`:** Restaura el estado previo exacto:
  - Detiene (`stop`) contenedores que estaban caídos o parados (`exited`, `stopped`, `dead`).
  - Pausa (`pause`) contenedores que estaban pausados.
  - Verifica y preserva contenedores que ya estaban en ejecución (`running`).
- **`DockerRestartTool` y `create_docker_restart_tool()`:** Instancia canónica de `AgentTool` con `risk_level=RiskLevel.HIGH`, `tool_type=ToolType.ACTUATOR`, `reversible=True`, `read_only=False` y `rollback_func=rollback_restart_container_fn`.

### 2.2 Registro en `plugins/jg_plugin_devops/plugin.py`
- `DevOpsPlugin.register_tools()` retorna `[create_docker_restart_tool()]`.

### 2.3 Sincronización en `plugins/jg_plugin_devops/planner.py`
- `_plan_from_incidents` asigna `tool_name="docker_restart"` con argumentos extraídos del incidente para el contenedor afectado.

### 2.4 Exportaciones en `plugins/jg_plugin_devops/__init__.py`
- Exportados `DockerRestartTool`, `DockerRestartArgs` y `create_docker_restart_tool` en `__all__`.

### 2.5 Batería de Pruebas en `plugins/jg_plugin_devops/tests/test_docker_tools.py`
- 12 pruebas específicas que validan:
  1. Validación de argumentos y bloqueo de inyecciones de comandos.
  2. Cumplimiento de contratos de `AgentTool`.
  3. Ejecución exitosa con cliente mockeado y poblado de `rollback_context`.
  4. Manejo de error de contenedor no encontrado (`NotFound`).
  5. Modo de simulación determinista (`DOCKER_SIMULATION_MODE=true`).
  6. Manejo de error cuando no existe socket Docker.
  7. Rollback deteniendo contenedor previamente `exited`.
  8. Rollback pausando contenedor previamente `paused`.
  9. Rollback verificando contenedor previamente `running`.
  10. Rollback en modo simulación.
  11. Rechazo de contextos de rollback corruptos o inválidos.
  12. Integración completa end-to-end con `rollback_node` de LangGraph y emisión de trazas de auditoría inmutables.

## 3. Verificación y Resultados

```bash
$ ./scripts/check.sh
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
96 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 96 source files

3️⃣  [Pytest] Ejecución de suite de tests (Core + Plugins)...
310 passed in 37.46s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```

### Comprobación en Vivo del Servicio (`jg_agente`):
```bash
$ curl -s http://localhost:8001/capabilities | jq .
{
  "plugins_count": 2,
  "tools_count": 3,
  "tools": [
    {
      "name": "get_weather",
      "category": "weather",
      "risk_level": "low",
      "reversible": false
    },
    {
      "name": "get_news",
      "category": "news",
      "risk_level": "low",
      "reversible": false
    },
    {
      "name": "docker_restart",
      "category": "devops",
      "risk_level": "high",
      "reversible": true
    }
  ],
  "engines_count": 3,
  "has_observer": true,
  "has_planner": true,
  "has_verifier": true
}
```
