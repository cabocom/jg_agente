## Resolución y Cierre de Issue #70

### Resumen de la Corrección
Se ha resuelto la saturación de cuota y caída prematura por errores `HTTP 429 Too Many Requests` en ejecuciones reflexivas del agente:

1. **Reintentos con Backoff Exponencial (`app/core/llm.py`):**
   - El cliente HTTP de modelos compatibles con OpenAI (`OpenAICompatibleChatModel`) ahora captura las respuestas `429`, parsea las cabeceras de control de tasa (`retry-after` y `x-ratelimit-reset-tokens`) y aplica hasta 3 reintentos transparentes con pausas progresivas.
2. **Poda de Salida de Herramientas (`plugins/jg_plugin_devops/docker_tools.py`):**
   - Se limitó el volumen de logs emitido por `docker_logs` a 1.800 caracteres para preservar la cuota TPM (8.000 tokens) ante llamadas consecutivas en `evaluate_node`.
3. **Validación de Pruebas:**
   - Nuevos tests automatizados añadidos en `tests/test_llm_retries.py` pasando al 100%.

**Commits asociados:**
- `#70 [AGENTE-LOGIC-05] Mitigación de Rate Limiting HTTP 429 con Reintentos Exponenciales y Truncado de Logs`
