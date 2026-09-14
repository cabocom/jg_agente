### ✅ Resolución y Cierre de Issue [AGENTE-SEC-08]

**Issue:** [jg_agente#64](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/64)
**Título:** [AGENTE-SEC-08] Fuga de Información Sensible e Interna en Respuestas de Error HTTP
**Severidad:** 🟡 MEDIO
**CWE:** CWE-209 (Generation of Error Message Containing Sensitive Information)

---

#### 1. Causa Raíz Identificada
En `jg_agente/app/api/executions.py`, cuando ocurría un error no controlado durante la ejecución del grafo o un fallo de sincronización con la base de datos, los bloques de captura devolvían cadenas sin procesar como `response=f"Error durante la ejecución del agente: {exc}"`, `error=str(exc)` o `error=str(db_err)` directamente en el cuerpo HTTP JSON. Esto exponía rutas internas del sistema de archivos, nombres de módulos, direcciones IP privadas y trazas de la base de datos a clientes externos (CWE-209).

#### 2. Cambios Implementados
- **Mensajes de Error Genéricos con ID de Incidencia (CWE-209):**
  - Se sustituyeron las respuestas con excepciones desnudas en `jg_agente/app/api/executions.py` por `GENERIC_EXECUTION_ERROR_MSG`, devolviendo al cliente un mensaje genérico seguro que referencia el ID de la incidencia (`execution_id`) para su reporte y seguimiento.
  - El campo `error` devuelto al cliente se sanitiza a `InternalExecutionError: Incidencia registrada con ID {execution_id}` en lugar de exponer la excepción cruda del backend.
- **Trazabilidad Interna Segura:**
  - El stacktrace completo se preserva de forma interna en los logs del servidor mediante `logger.exception(...)` y en la columna de base de datos interna `core_executions.error`.
- **Pruebas Automatizadas:**
  - Se implementó `test_trigger_execution_uncaught_error_sanitized_response` en `test_api_executions_trigger.py`, verificando que excepciones con credenciales simuladas, IPs internas o rutas del sistema no se filtren en la respuesta HTTP JSON.
- **Optimización de Pruebas Unitarias:**
  - Se aisló la prueba de autenticación `test_valid_request_passes_authentication` en `test_api_executions_auth.py` inyectando un mock del grafo de ejecución con `MockChatModel`, eliminando el timeout síncrono de 30s y reduciendo el tiempo de la suite completa de 33s a 3.09s.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Tipado estricto y formato 100% limpios sin advertencias (`Success: no issues found in 44 source files`).
- **Pytest:** 312/312 tests pasando en 3.09s (`jg_agente/tests`).
