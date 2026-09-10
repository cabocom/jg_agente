# Implementación y comportamiento

`AgentTool.timeout_sec` es descriptivo: `AgentTool.run()` llama a `func` directamente y `SecurityGuard.execute_tool()` no impone límite temporal. Un SDK bloqueado puede bloquear el worker. Los resultados de persistencia se degradan a log y memoria (`_persist_or_update_execution` captura cualquier excepción), por lo que una respuesta exitosa no demuestra que exista trazabilidad durable.

El mecanismo HITL pausa mediante `interrupt()` y se reanuda por `Command(resume=...)`; el flujo interno existe. La API que lo controla no comprueba la identidad del llamador, por lo que la correcta semántica interna no constituye una barrera de autorización.

La herramienta RSS valida DNS antes de usar el cliente HTTP. En este entorno sin DNS falla antes de que los tests puedan simular la petición; no hay fallback ante una política/entorno sin resolución. Véase AGENT-005.
