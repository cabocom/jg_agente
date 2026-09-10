# Issues propuestos — jg_agente

- **ISSUE-AGENT-001 (HIGH):** Autenticar/autorizar y proteger contra replay todos los endpoints de Execution Plane. Resuelve AGENT-001; coordinar contrato con DASH-001.
- **ISSUE-AGENT-002 (HIGH):** Eliminar socket Docker y ejecución root del agente general; diseñar executor privilegiado acotado. Resuelve AGENT-002.
- **ISSUE-AGENT-003 (HIGH):** Aislar `agent_id` en tablas, checkpoints y rutas de ejecución multiinstancia. Resuelve AGENT-003; depende de diseño GLOBAL-002.
- **ISSUE-AGENT-004 (MEDIUM):** Aplicar y probar `timeout_sec` y cancelación de herramientas. Resuelve AGENT-004.
- **ISSUE-AGENT-005 (MEDIUM):** Corregir contrato SSRF/fallback del tool News y sus pruebas sin depender de DNS externo. Resuelve AGENT-005.
- **ISSUE-AGENT-006 (MEDIUM):** Definir semántica de fallo de persistencia y propagar estado coherente. Resuelve AGENT-006.
- **ISSUE-AGENT-007 (LOW):** Persistir credenciales atómicamente. Resuelve AGENT-007.
