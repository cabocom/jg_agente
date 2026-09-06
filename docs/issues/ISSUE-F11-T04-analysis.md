# Análisis Técnico: [ISSUE-F11-T04] Implementación de herramientas Docker con rollback_func en plugin DevOps

## 1. Problema y Objetivos Técnicos
La infraestructura de `jg_agente` requería dotar al agente de capacidades de accionamiento y remediación autónoma sobre contenedores Docker, garantizando al mismo tiempo que cualquier fallo operacional posterior pueda ser revertido de manera predecible y segura.

### Objetivos:
1. Diseñar el esquema validado de entrada `DockerRestartArgs` previniendo inyecciones de comandos en nombres de contenedor y garantizando rangos seguros de timeout.
2. Implementar la función de ejecución `restart_container_fn` con captura del estado pre-operacional en `rollback_context`.
3. Implementar la función de compensación `rollback_restart_container_fn` para restaurar el estado anterior exacto (`exited` -> `stop`, `paused` -> `pause`, `running` -> verificar operatividad).
4. Instanciar la herramienta canónica `DockerRestartTool` bajo `AgentTool` con `risk_level=RiskLevel.HIGH`, `reversible=True` y `rollback_func` registrado.
5. Conectar la herramienta al `DevOpsPlugin.register_tools()` y al generador de planes `DAGPlannerEngine`.
6. Garantizar aislamiento estricto del Core y modo dual/simulación para entornos CI/CD sin daemon Docker.

## 2. Decisiones de Diseño y Arquitectura

### 2.1 Nombre del Módulo (`docker_tools.py`)
Dado que `plugins/jg_plugin_devops` se encuentra en el `PYTHONPATH`, nombrar el archivo como `docker.py` colisionaría con el SDK oficial de Python `import docker`. Por ello, se nombró `docker_tools.py`.

### 2.2 Validación de Seguridad Anti-Inyección
```python
CONTAINER_NAME_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
```
Se normalizan barras iniciales (`lstrip("/")`) que suele emitir la API de Docker y se rechazan metacaracteres de shell (`&`, `;`, `|`, `$`, espacios, acentos graves).

### 2.3 Estructura de `rollback_context`
El resultado de la ejecución genera un diccionario inmutable en `ToolResult.rollback_context`:
```python
{
    "container": "web_api",
    "container_id": "c1234567890abcdef",
    "previous_state": "exited",
    "post_state": "running",
    "action": "restart",
    "timestamp": "2026-09-06T10:48:00Z"
}
```

### 2.4 Lógica de Compensación en `rollback_func`
- **Si `previous_state in ("exited", "stopped", "dead", "created")`:** Invoca `container.stop(timeout=10)` para restaurar el estado inactivo previo.
- **Si `previous_state == "paused"`:** Invoca `container.pause()`.
- **Si `previous_state == "running"`:** Verifica que el contenedor permanece en ejecución activa sin interrumpir el servicio.
- **Modo Simulado / Fallback:** Si `DOCKER_SIMULATION_MODE=true`, produce un resultado determinista sin necesidad de dependencias externas.

## 3. Integración con el Flujo de Grafo LangGraph
En `app/nodes/execute.py`, el `StepExecutionRecord` almacena el `rollback_context` devuelto por el `ToolResult`. Si el plan falla en un paso posterior o el nodo `verify` reporta que el incidente persiste, `app/nodes/rollback.py` (`rollback_node`) itera en orden inverso sobre los pasos completados, identificando las herramientas con `tool.reversible is True` y ejecutando `tool.rollback(record.rollback_context)`.
