# Análisis Técnico - Issue [AGENTE-SEC-09]

## Información del Issue
- **ID:** [jg_agente#65](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/65)
- **Título:** [AGENTE-SEC-09] Condición de Carrera TOCTOU / DNS Rebinding en Validador SSRF
- **Severidad:** 🟡 MEDIO
- **CWE:** CWE-367 (Time-of-check Time-of-use Race Condition)
- **Ubicación:** `jg_agente/app/security/ssrf.py:239-264`

---

## 1. Causa Raíz Identificada

En la implementación previa de `SSRFValidator`:
1. **Condición de Carrera TOCTOU (Time-of-Check Time-of-Use):**
   - Durante la fase de validación (`validate_url`), el validador resuelve el nombre de dominio mediante DNS y verifica que las IPs devueltas no pertenezcan a rangos privados o restringidos (RFC 1918, metadata de nube, loopback, etc.).
   - Sin embargo, una vez superada la validación, la herramienta HTTP cliente (como `httpx.Client()` en `news.py`) realiza una conexión a la URL original resolviendo de nuevo el nombre de dominio en una consulta DNS independiente.
   - Si el atacante controla el servidor de nombres autoritativo del dominio o utiliza técnicas de DNS Rebinding (con TTL=0):
     - Consulta 1 (Tiempo de Validación / Check): Responde con IP pública (ej. `93.184.216.34`), pasando la validación SSRF.
     - Consulta 2 (Tiempo de Conexión / Use): Responde con IP privada local (ej. `127.0.0.1` o `169.254.169.254`), evadiendo completamente la protección SSRF y accediendo a servicios internos.

2. **Bloqueo Síncrono del Event Loop:**
   - La llamada `socket.getaddrinfo()` se ejecuta de forma síncrona en el hilo principal, bloqueando el bucle de eventos de `asyncio` durante latencias de resolución DNS lentas o fallidas.

---

## 2. Estrategia de Solución

1. **Fijación de IP (DNS Pinning):**
   - Proporcionar funciones `resolve_and_pin_url()` y `resolve_and_pin_url_async()` que devuelvan:
     - La IP pública validada.
     - La URL con el host fijado a dicha IP literal (`pinned_url`).
     - La cabecera `Host: <original_hostname>` requerida para HTTP virtual hosting.
2. **Resolución DNS Asíncrona:**
   - Implementar `validate_url_async()` utilizando `asyncio.get_running_loop().getaddrinfo()` para evitar bloqueos del bucle de eventos.
3. **Transporte Seguro para HTTPX (`SSRFSafeTransport`):**
   - Implementar un transporte seguro para `httpx` que enlace la conexión TCP directamente con la IP validada en el momento de la apertura del socket (`connect_tcp`), garantizando que la IP comprobada y la IP conectada sean idénticas.
   - Preservar `server_hostname` para que la validación del certificado SSL y la extensión TLS SNI funcionen con normalidad en conexiones HTTPS.
4. **Adopción en Plugins:**
   - Integrar la fijación de IP y cliente seguro en `news.py`.
