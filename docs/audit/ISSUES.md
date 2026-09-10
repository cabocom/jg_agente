# Issues propuestos — jg_agente

- **ISSUE-AGENT-001 (HIGH):** `[COMPLETADO]` Autenticar/autorizar y proteger contra replay todos los endpoints de Execution Plane (Firma canónica HMAC-SHA256, cabeceras X-Signature, X-Timestamp, X-Agent-ID, anti-replay $\pm 300\text{ s}$). Resuelve AGENT-001 (GLOBAL-001).
- **ISSUE-AGENT-002 (HIGH):** Eliminar socket Docker y ejecución root del agente general; diseñar executor privilegiado acotado. Resuelve AGENT-002.
- **ISSUE-AGENT-003 (HIGH):** `[COMPLETADO]` Aislar `agent_id` en tablas, checkpoints y rutas de ejecución multiinstancia (Bases de datos dedicadas `jg_agente_conversacional` y `jg_agente_devops`). Resuelve AGENT-003 (GLOBAL-002).
- **ISSUE-AGENT-004 (MEDIUM):** `[COMPLETADO]` Aplicar y probar `timeout_sec` y cancelación de herramientas (SecurityGuard.execute_tool async, asyncio.to_thread no bloqueante, execute_node con StepStatus.FAILED y TOOL_TIMEOUT). Resuelve AGENT-004.
- **ISSUE-AGENT-005 (MEDIUM):** Corregir contrato SSRF/fallback del tool News y sus pruebas sin depender de DNS externo. Resuelve AGENT-005.
- **ISSUE-AGENT-006 (MEDIUM):** Definir semántica de fallo de persistencia y propagar estado coherente. Resuelve AGENT-006.
- **ISSUE-AGENT-007 (LOW):** Persistir credenciales atómicamente. Resuelve AGENT-007.

