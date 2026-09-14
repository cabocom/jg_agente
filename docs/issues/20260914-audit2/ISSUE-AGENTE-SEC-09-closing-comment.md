### ✅ Resolución y Cierre de Issue [AGENTE-SEC-09]

**Issue:** [jg_agente#65](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/65)
**Título:** [AGENTE-SEC-09] Condición de Carrera TOCTOU / DNS Rebinding en Validador SSRF
**Severidad:** 🟡 MEDIO
**CWE:** CWE-367 (Time-of-check Time-of-use Race Condition)

---

#### 1. Causa Raíz Identificada
El validador de SSRF (`SSRFValidator.validate_url`) resolvía el nombre de host mediante `socket.getaddrinfo()` y comprobaba que ninguna IP perteneciera a rangos privados o de metadatos. Sin embargo, las herramientas cliente (como `news_tool` vía `httpx`) ejecutaban posteriormente una nueva petición HTTP delegando una segunda resolución DNS al sistema operativo. Esto abría una ventana TOCTOU (CWE-367) vulnerable a ataques de DNS Rebinding: un servidor DNS controlado por un atacante con TTL=0 respondía con una IP pública en la primera comprobación y con `127.0.0.1` o `169.254.169.254` en la segunda petición. Además, `socket.getaddrinfo()` se invocaba sincrónicamente, bloqueando el event loop de `asyncio`.

#### 2. Cambios Implementados
- **Resolución Asíncrona No Bloqueante:**
  - Se añadieron `resolve_host_async` y `validate_url_async` utilizando `asyncio.get_running_loop().getaddrinfo()` para garantizar que la resolución no bloquee el event loop en flujos asíncronos.
- **DNS Pinning a Nivel de Aplicación:**
  - Se implementaron `resolve_and_pin_url()` y `resolve_and_pin_url_async()` en `SSRFValidator`, que validan exhaustivamente todas las IPs asociadas y fijan la dirección IP comprobada en metadatos de conexión (`pinned_ip`, `dns_pin_map`, cabecera `Host` original preservada).
- **Protección a Nivel de Socket TCP (`httpcore` / `httpx`):**
  - Se implementaron `SSRFSafeSyncBackend` y `SSRFSafeAsyncBackend` heredando de los backends de `httpcore`. Al invocar `connect_tcp`, el socket se abre directamente contra la IP fijada y se comprueba estrictamente contra listas de bloqueo antes de emitir tráfico de red.
  - Se crearon los transportes `SSRFSafeTransport` y `SSRFSafeAsyncTransport` junto con las funciones fábrica `create_ssrf_safe_client()` y `create_async_ssrf_safe_client()`.
- **Actualización de Consumidores:**
  - La herramienta `news_tool` en `jg_agente/plugins/jg_plugin_conversational/news.py` se actualizó para emplear `resolve_and_pin_url` y `create_ssrf_safe_client`.
- **Cobertura de Pruebas Unitarias:**
  - Se añadió la clase `TestSSRFAsyncAndDNSPinning` en `tests/test_ssrf_validator.py` cubriendo validación asíncrona, DNS Pinning, simulación de bloqueo de DNS Rebinding dinámico y creación de clientes seguros.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Tipado estricto y formato 100% limpios sin advertencias (`Success: no issues found in 106 source files`, 106 archivos formateados).
- **Pytest Agente:** 395/395 tests pasando con éxito (`jg_agente/scripts/check.sh`).
- **Verificación Global (`./check_unit.sh`):**
  - `jg_agente`: PASÓ (Ruff, MyPy y Pytest correctos).
  - `jg_dashboard`: PASÓ (Pest, 255 tests y 1222 aserciones correctas).
