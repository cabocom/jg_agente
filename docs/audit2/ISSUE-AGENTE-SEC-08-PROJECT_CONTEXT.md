# Contexto de Proyecto - Issue [AGENTE-SEC-08]

## Información General
- **Repositorio:** `jg_agente`
- **Issue:** [jg_agente#64](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/64)
- **Título:** [AGENTE-SEC-08] Fuga de Información Sensible e Interna en Respuestas de Error HTTP
- **Severidad:** 🟡 MEDIO
- **CWE:** CWE-209 (Generation of Error Message Containing Sensitive Information)

## Módulos y Archivos Involucrados
1. `jg_agente/app/api/executions.py`:
   - `execute_graph_pipeline`: saneamiento de `agent_output.response` y `agent_output.error` ante excepciones no controladas mediante `GENERIC_EXECUTION_ERROR_MSG`.
   - Bloques de degradación de persistencia: saneamiento de `error` en `PersistenceMetadata` mediante `GENERIC_PERSISTENCE_ERROR_MSG`.
2. `jg_agente/tests/test_api_executions_trigger.py`:
   - `test_trigger_execution_uncaught_error_sanitized_response`: test de verificación de no-fuga de credenciales, rutas o IPs en respuestas de error.
