# Walkthrough - ISSUE-F09-T03: Implementación de NewsTool en jg_plugin_conversational

## 1. Ficheros Modificados y Creados
- **Nuevo:** `plugins/jg_plugin_conversational/news.py`
  - Definición del esquema `NewsArgs` con límites y validación regex.
  - Implementación de `get_news_fn` con validación SSRF, petición HTTP con timeout de 5 segundos, parseo seguro de feed RSS XML y simulación determinista fallback.
  - Factoría `create_news_tool` con metadatos canónicos de `AgentTool`.
- **Modificado:** `plugins/jg_plugin_conversational/plugin.py`
  - Registro de `create_news_tool()` en el método `register_tools()`.
  - Inclusión de `"news"` en los tags de metadatos del plugin.
- **Modificado:** `plugins/jg_plugin_conversational/__init__.py`
  - Exportación pública de `NewsArgs` y `create_news_tool`.
- **Nuevo:** `plugins/jg_plugin_conversational/tests/test_news_tool.py`
  - Suite de 7 pruebas unitarias:
    - Validación y rechazo de temas inválidos (caracteres no permitidos, longitud).
    - Ejecución exitosa y estructura de `ToolResult`.
    - Simulación determinista con topics temáticos.
    - Parseo de XML RSS con mocks de `httpx`.
    - Mitigación SSRF ante URLs maliciosas.
    - Manejo de timeouts HTTP y degradación elegante.
    - Registro formal en `ConversationalPlugin` y `CapabilityRegistry`.
- **Modificado:** `plugins/jg_plugin_conversational/tests/test_weather_tool.py` y `test_plugin.py`
  - Actualización de aserciones para el conteo de 2 herramientas registradas en el plugin (`get_weather` y `get_news`).

## 2. Validación de Seguridad
- **SSRF:** Toda petición HTTP saliente valida la URL de destino contra rangos IP privados (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`) y direcciones de enlace local Cloud IMDS (`169.254.0.0/16`).
- **SEC-06:** Los resultados devueltos por `get_news` son exclusivamente datos de noticias formateados sin instrucciones en lenguaje natural dirigidas al modelo.
