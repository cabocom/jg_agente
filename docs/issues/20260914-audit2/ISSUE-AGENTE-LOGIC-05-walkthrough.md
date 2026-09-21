# Walkthrough - [AGENTE-LOGIC-05] Saturación de Cuota TPM (HTTP 429) por Salidas Masivas de Herramientas y Ausencia de Reintentos

## Resumen Ejecutivo

- **Issue:** [jg_agente#70](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/70) - `[AGENTE-LOGIC-05] Saturación de Cuota TPM (HTTP 429) por Salidas Masivas de Herramientas y Ausencia de Reintentos`
- **Severidad:** 🔴 ALTO / RESILIENCIA OPERATIVA
- **Componentes Afectados:**
  - [`app/core/llm.py`](../../../app/core/llm.py)
  - [`plugins/jg_plugin_devops/docker_tools.py`](../../../plugins/jg_plugin_devops/docker_tools.py)
  - [`app/core/config.py`](../../../app/core/config.py)
  - [`tests/test_llm_retries.py`](../../../tests/test_llm_retries.py)

---

## Causa Raíz

1. **Falta de tolerancia a fallos transitorios en el cliente HTTP del LLM:**
   El método `_agenerate` invocaba `resp.raise_for_status()` inmediatamente tras el `POST`. Si el proveedor (Groq) enviaba un `429 Too Many Requests` solicitando una espera de apenas 2.5 segundos (`x-ratelimit-reset-tokens: 2.5s`), el pipeline abortaba sin reintentar.
2. **Volumen de tokens inflado por herramientas:**
   `docker_logs` permitía salidas de hasta 6.000 caracteres, agotando la cuota TPM (8.000 tokens) de Groq en la iteración reflexiva siguiente (`evaluate_node`).

---

## Solución Implementada

1. **Reintentos Automáticos con Backoff Exponencial y Lectura de Headers en `llm.py`:**
   - Se implementó un bucle de hasta 3 reintentos (`max_retries = 3`).
   - Se procesan dinámicamente las cabeceras `retry-after` y `x-ratelimit-reset-tokens` (soportando sufijos `s` y `ms`).
   - Se aplica pausa asíncrona no bloqueante (`await asyncio.sleep(wait_seconds)`).
   - Se registra advertencia con nivel de log apropiado sin alertar falsamente al usuario.

2. **Optimización de Salida en `docker_tools.py`:**
   - Se redujo el tope máximo de caracteres de `docker_logs` a 1.800 caracteres (`max_log_chars = 1800`), previniendo picos que colisionen con los límites por minuto de la API.

3. **Flexibilización de Configuración en `config.py`:**
   - Soporte para parametrización de proveedores y claves de API alternativas (`GEMINI_API_KEY`, etc.).

4. **Suite de Pruebas Automatizadas:**
   - Creado [`tests/test_llm_retries.py`](../../../tests/test_llm_retries.py) con 2 casos de prueba:
     - `test_llm_retries_on_429_success`: valida reintento automático y respuesta exitosa tras HTTP 429.
     - `test_llm_raises_after_max_retries`: valida elevación de excepción tras agotar el número máximo de reintentos permitidos.

---

## Verificación y Resultados

```bash
$ jg_agente/.venv/bin/pytest jg_agente/tests/test_llm_retries.py
============================== test session starts ==============================
collected 2 items

jg_agente/tests/test_llm_retries.py ..                                    [100%]

=============================== 2 passed in 4.05s ===============================
```
```bash
$ jg_agente/.venv/bin/pytest jg_agente/plugins/jg_plugin_devops/tests/test_docker_tools.py
============================== test session starts ==============================
collected 18 items

jg_agente/plugins/jg_plugin_devops/tests/test_docker_tools.py .................. [100%]

============================== 18 passed in 0.56s ===============================
```
