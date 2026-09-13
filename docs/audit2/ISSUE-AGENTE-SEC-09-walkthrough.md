# Walkthrough: Remediación AGENTE-SEC-09 (CWE-367 / TOCTOU SSRF & DNS Rebinding)

## 1. Resumen de la Intervención
- **Vulnerabilidad remediada:** [jg_agente#65](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/65) - `[AGENTE-SEC-09] Condición de Carrera TOCTOU / DNS Rebinding en Validador SSRF`.
- **CWE:** CWE-367 (Time-of-check Time-of-use Race Condition).
- **Severidad:** 🟡 MEDIO.
- **Alcance:**
  - `jg_agente/app/security/ssrf.py`: Incorporación de resolución DNS asíncrona no bloqueante, métodos de DNS Pinning (`resolve_and_pin_url`, `resolve_and_pin_url_async`), backends personalizados de red para `httpcore` (`SSRFSafeSyncBackend`, `SSRFSafeAsyncBackend`), transportes seguros para `httpx` (`SSRFSafeTransport`, `SSRFSafeAsyncTransport`) y fábricas de clientes HTTP (`create_ssrf_safe_client`, `create_async_ssrf_safe_client`).
  - `jg_agente/app/security/__init__.py`: Exportación de las nuevas interfaces y clientes seguros.
  - `jg_agente/plugins/jg_plugin_conversational/news.py`: Actualización del cliente HTTP de `news_tool` para usar `resolve_and_pin_url` y `create_ssrf_safe_client`.
  - `jg_agente/tests/test_ssrf_validator.py`: Suite integral de pruebas para DNS Pinning, mitigación de DNS Rebinding / TOCTOU y validación asíncrona.

---

## 2. Cambios de Código Detallados

### A. Validador SSRF (`jg_agente/app/security/ssrf.py`)
1. **Resolución Asíncrona sin Bloqueo de Event Loop:**
   - `resolve_host(hostname, port)` para resolución sincrónica con `socket.getaddrinfo`.
   - `resolve_host_async(hostname, port)` delegando en `asyncio.get_running_loop().getaddrinfo()` para evitar bloqueos del event loop de FastAPI / Agente.
   - Métodos `validate_url_async()`, `is_safe_url_async()` y `assert_safe_url_async()`.
2. **DNS Pinning:**
   - `resolve_and_pin_url(url)` y `resolve_and_pin_url_async(url)`: Validan el destino, resuelven la dirección IP, comprueban todas las IPs contra rangos prohibidos/RFC 1918/Metadata y seleccionan una IP segura fijada (`pinned_ip`).
   - Generan un mapa de fijación de DNS (`dns_pin_map`), URL con IP fijada (`pinned_url`), y cabecera `Host` con el nombre de dominio original para preservar compatibilidad con Virtual Hosts y SNI TLS.
3. **Backends y Transportes de Red a Nivel TCP:**
   - `SSRFSafeSyncBackend` y `SSRFSafeAsyncBackend`: Interceptan la apertura del socket TCP en `connect_tcp`. Si un host está fijado en el mapa de DNS, conectan directamente a dicha IP. Si no lo está, resuelven y validan la IP antes de abrir el socket. Si la IP resultante pertenece a rangos privados o prohibidos, lanzan inmediatamente `SSRFValidationError` a nivel TCP antes de emitir ningún paquete.
   - `SSRFSafeTransport` y `SSRFSafeAsyncTransport`: Transportes HTTP/HTTPS para `httpx` integrados con `httpcore.ConnectionPool` / `httpcore.AsyncConnectionPool`, preservando verificación TLS, certificados y cabeceras.
   - `create_ssrf_safe_client()` y `create_async_ssrf_safe_client()`: Clientes listos para uso seguro en cualquier plugin o herramienta.

### B. Herramienta de Noticias (`jg_agente/plugins/jg_plugin_conversational/news.py`)
- Se sustituyó la doble resolución (validación previa + posterior `httpx.Client.get`) por:
  ```python
  is_valid, reason, pin_info = ssrf_validator.resolve_and_pin_url(rss_url)
  ...
  with create_ssrf_safe_client(
      dns_pin_map=pin_info.get("dns_pin_map"),
      validator=ssrf_validator,
      timeout=5.0,
  ) as client:
      resp = client.get(rss_url, headers=headers)
  ```

### C. Suite de Pruebas (`jg_agente/tests/test_ssrf_validator.py`)
- `test_validate_url_async_blocks_private`: Valida bloqueo asíncrono de IPs privadas.
- `test_validate_url_async_allows_public`: Valida URLs públicas en modo asíncrono.
- `test_assert_safe_url_async_raises`: Verifica excepciones `SSRFValidationError` asíncronas.
- `test_resolve_and_pin_url_with_mocked_dns`: Comprueba fijación y estructura de metadatos de DNS Pinning.
- `test_resolve_and_pin_url_blocks_rebinding_to_private`: Simula intento de DNS rebinding donde un dominio dinámico apunta a `127.0.0.1` y es rechazado.
- `test_resolve_and_pin_url_async_with_mocked_dns`: Valida fijación asíncrona.
- `test_ssrf_safe_backend_blocks_private_connection`: Valida que el backend a nivel TCP rechaza conexiones si la IP fijada o resuelta pertenece a rangos RFC 1918.
- `test_ssrf_safe_transport_and_client_creation` y `test_async_ssrf_safe_transport_and_client_creation`: Valida creación correcta de clientes síncronos y asíncronos.

---

## 3. Verificación y Resultados
1. **Linter & Formato (`Ruff`):**
   - 100% de archivos formateados y limpios sin advertencias (`All checks passed!`, 106 archivos).
2. **Tipado Estático (`MyPy`):**
   - Modo estricto superado sin errores (`Success: no issues found in 106 source files`).
3. **Pruebas Unitarias Agente (`Pytest`):**
   - 395/395 tests pasando con éxito.
4. **Verificación Global (`./check_unit.sh`):**
   - `jg_agente`: PASÓ (Ruff, MyPy y Pytest correctos).
   - `jg_dashboard`: PASÓ (Pest, 255 tests y 1222 aserciones correctas).
