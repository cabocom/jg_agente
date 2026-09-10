# Análisis Técnico: [ISSUE-AGENT-005] Fallback offline y resolución de tests en NewsTool

## 1. Diagnóstico del Estado Previo
En la implementación previa de `plugins/jg_plugin_conversational/news.py`:
- `get_news_fn()` invocaba el validador SSRF del core:
  ```python
  is_valid, reason = ssrf_validator.validate_url(rss_url)
  if not is_valid:
      logger.error("Bloqueo SSRF al intentar consultar RSS de noticias: %s (%s)", rss_url, reason)
      raise SSRFValidationError(f"Destino de noticias no autorizado por política SSRF: {reason}")
  ```
- En un entorno offline, contenedor de pruebas o máquina sin DNS configurado hacia el exterior:
  - `ssrf_validator.validate_url("https://www.europapress.es/...")` ejecutaba `socket.getaddrinfo("www.europapress.es", ...)`.
  - Dicha llamada fallaba con `socket.gaierror` (`[Errno -3] Temporary failure in name resolution` o `[Errno 8] nodename nor servname provided, or not known`).
  - `validate_url` devolvía `(False, "Fallo en resolución DNS: ...")`.
  - Como consecuencia, `news.py` trataba el error de DNS indistintamente como una infracción grave de seguridad SSRF, arrojando `SSRFValidationError` y abortando la ejecución.
- Esto impedía que la herramienta ejecutara el bloque de fallback determinista (`_get_simulated_news(topic, limit)`), diseñado precisamente para entornos de desarrollo y contingencia.
- Asimismo, las pruebas unitarias que interceptaban la capa HTTP (`httpx.Client`) fallaban cuando se ejecutaban en entornos sin salida a internet, ya que la excepción se producía en el paso de validación DNS previo.

## 2. Solución Diseñada

### 2.1 Discriminación Semántica del Rechazo SSRF
En `news.py`:
1. Al evaluar el resultado `(is_valid, reason)` de `validate_url`:
   - Si `is_valid` es `False`, se analiza la cadena `reason`.
   - Si contiene patrones típicos de indisponibilidad DNS (`"resolución dns"`, `"resolver"`, `"dns"`, `"nodename nor servname"`), se marca `is_dns_failure = True`.
   - Se registra una advertencia con `logger.warning`.
   - Se omite el bloque de petición HTTP (`httpx.Client`) y se procede directamente al paso de fallback determinista.
2. Si `is_valid` es `False` por una razón distinta (por ejemplo, resolución a IP privada, red loopback, IP link-local IMDS `169.254.169.254`, etc.):
   - Se registra con `logger.error`.
   - Se eleva `SSRFValidationError(f"Destino de noticias no autorizado por política SSRF: {reason}")`.
   - Esto garantiza que el blindaje de seguridad anti-SSRF permanezca al 100% intacto.

### 2.2 Sincronización con el Contrato de la Herramienta
- La función de fallback `_get_simulated_news(topic, limit)` construye un resultado coherente:
  - `ToolResult(success=True, output=..., duration_ms=..., metadata={"topic": topic, "count": len(simulated), "articles": simulated, "source": "simulated"})`.
- Los textos generados no contienen instrucciones directas para el modelo (prevención SEC-06).

### 2.3 Resiliencia y Determinismo en Tests Unitarios
En `plugins/jg_plugin_conversational/tests/test_news_tool.py`:
- `test_news_xml_parsing_mocked_http`: Se mockea `socket.getaddrinfo` retornando una tupla con una IP pública legítima (`195.55.100.1`), permitiendo que el validador SSRF pase exitosamente sin salir a la red y pruebe el parser de XML RSS bajo el mock de `httpx.Client`.
- `test_news_offline_dns_failure_fallback`: Simula un fallo de DNS lanzando `socket.gaierror(-3, "Temporary failure in name resolution")` y verifica que el resultado devuelto es `success=True` con fuente `simulated`.
- `test_news_real_ssrf_violation_raises`: Simula una IP de loopback (`127.0.0.1`) y verifica que se eleva `SSRFValidationError` sin activar el fallback simulado.
