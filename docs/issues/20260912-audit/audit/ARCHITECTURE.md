# Arquitectura observada

El proceso FastAPI construye `CapabilityRegistry` y `PluginManager`, arranca plugins y forma el grafo bajo demanda en `get_agent_graph`. `GraphBuilder` no contiene ramas por dominio y construye la topología a partir de engines registrados; este punto sí respalda el agnosticismo del Core a nivel de código.

La frontera no está protegida: los routers `/executions` y telemetría se montan sin dependencia o middleware de autenticación en `app/main.py`. El HMAC emitido por Dashboard no se consume en ningún módulo del agente.

La arquitectura documentada de múltiples instancias no está materializada en la base de datos compartida: `CoreExecution` sólo indexa `execution_id` y `thread_id`; no tiene `agent_id`. Los checkpoints se configuran también sin namespace de agente. Dos contenedores con la misma BD pueden colisionar por `thread_id`.

El autodescubrimiento añade `PLUGINS_DIR` a `sys.path` e importa paquetes locales. Es aceptable para plugins entregados con la imagen, pero no es aislamiento de plugins: se ejecutan en el mismo intérprete y proceso.
