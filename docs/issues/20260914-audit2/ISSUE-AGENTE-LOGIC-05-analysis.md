# Análisis Técnico: [AGENTE-LOGIC-05] Saturación de Cuota TPM (HTTP 429) por Salidas Masivas de Herramientas y Ausencia de Reintentos

## Diagnóstico y Estado Previo

### 1. Invocación inmediata sin reintentos en `OpenAICompatibleChatModel`
En [`app/core/llm.py`](../../../app/core/llm.py):
```python
async with httpx.AsyncClient(timeout=60.0) as client:
    resp = await client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
```
Cualquier limitación transitoria de tasa (HTTP 429) lanzaba un `httpx.HTTPStatusError` de forma inmediata, ignorando las cabeceras estándar de control de congestión (`retry-after`, `x-ratelimit-reset-tokens`).

### 2. Inyección de volúmenes excesivos de texto en herramientas DevOps
En [`plugins/jg_plugin_devops/docker_tools.py`](../../../plugins/jg_plugin_devops/docker_tools.py):
```python
max_log_chars = 6000
if len(log_str) > max_log_chars:
    log_str = log_str[-max_log_chars:]
```
Un límite de 6.000 caracteres representa entre 1.500 y 1.800 tokens únicamente en la salida de una sola herramienta. Al concatenarse con el prompt del sistema, las definiciones de esquemas JSON de 4 herramientas y la conversación previa, la petición alcanzaba los 5.000+ tokens. Al realizar la siguiente invocación reflexiva en `evaluate_node`, se sobrepasaba el límite estricto de 8.000 TPM de Groq.

---

## Estrategia de Mitigación

1. **Bucle de Reintentos con Backoff Exponencial y Detección de Rate Limit en `llm.py`:**
   - Capturar el código de estado HTTP `429`.
   - Extraer las cabeceras `retry-after` y `x-ratelimit-reset-tokens` (soportando formatos en segundos y milisegundos).
   - En caso de ausencia, aplicar un backoff progresivo base: `wait_seconds = 2.5 * (attempt + 1)`.
   - Reintentar hasta 3 veces de forma transparente antes de lanzar el error.

2. **Acotamiento del Truncado de Seguridad en `docker_tools.py`:**
   - Reducir `max_log_chars` de 6.000 a 1.800 caracteres (~350-400 tokens).
   - Garantizar suficiente información de diagnóstico operacional sin comprometer la ventana de tokens por minuto del modelo cognitivo.

3. **Verificación Automatizada:**
   - Crear suite de pruebas `tests/test_llm_retries.py` con simulación mock de respuestas HTTP 429 y comprobación de reintentos exitosos y límite máximo.
