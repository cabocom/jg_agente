# Contexto del Proyecto: AGENTE-SEC-09 (CWE-367 / TOCTOU SSRF & DNS Rebinding)

## 1. Módulo Afectado
- **Ruta principal:** `jg_agente/app/security/ssrf.py`
- **Consumidores directos:** `jg_agente/plugins/jg_plugin_conversational/news.py` (y cualquier plugin o herramienta que realice peticiones HTTP salientes).
- **CWE:** CWE-367 (Time-of-check Time-of-use Race Condition)
- **Severidad:** 🟡 MEDIO

---

## 2. Análisis del Problema
1. **Doble resolución DNS (TOCTOU):**
   - El validador `validate_url` ejecutaba `socket.getaddrinfo(hostname, ...)` comprobando que la IP resuelta no perteneciera a subredes privadas, de loopback ni de metadatos de nube.
   - Posteriormente, herramientas cliente como `news_tool` o clientes `httpx` invocaban `httpx.get(url)`, delegando una nueva resolución DNS al sistema operativo.
   - Si un atacante controla el servidor DNS autoritativo con un TTL muy bajo (0 o 1 segundo), la primera resolución devolvía una IP pública legítima superando la validación, y la segunda resolución devolvía `127.0.0.1` o `169.254.169.254` (ataque clásico de DNS Rebinding).
2. **Bloqueo del bucle de eventos (`asyncio`):**
   - La llamada sincrónica `socket.getaddrinfo` dentro de flujos asíncronos bloquea el event loop del servidor FastAPI/Agente.

---

## 3. Estrategia de Remediación
1. **Resolución Asíncrona No Bloqueante:**
   - Implementación de `resolve_host_async` y `validate_url_async` delegando en `asyncio.get_running_loop().getaddrinfo()` para evitar bloqueos del event loop.
2. **DNS Pinning:**
   - Métodos `resolve_and_pin_url(url)` y `resolve_and_pin_url_async(url)` que validan y congelan la dirección IP comprobada.
   - `SSRFSafeSyncBackend` y `SSRFSafeAsyncBackend` para `httpcore` / `httpx` que aseguran que el socket TCP se abra directamente contra la IP validada (`target_ip`), verificando en el instante mismo de la conexión (`connect_tcp`) que no pertenezca a rangos prohibidos.
   - Preservación íntegra de cabeceras HTTP (`Host: <dominio>`) y SNI TLS (`server_hostname=<dominio>`), garantizando compatibilidad con HTTPS y certificados SSL.
3. **Transportes y Clientes Seguros:**
   - `SSRFSafeTransport` y `SSRFSafeAsyncTransport` con factory `create_ssrf_safe_client()` para uso inmediato por plugins y herramientas.
4. **Actualización de Consumidores:**
   - Modificación de `news.py` para utilizar `resolve_and_pin_url` y `create_ssrf_safe_client`.
