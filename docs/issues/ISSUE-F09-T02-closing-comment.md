Se ha completado la implementación de **[ISSUE-F09-T02] Implementación de WeatherTool en jg_plugin_conversational** en `jg_agente`.

### Resumen de Cambios:
1. **Módulo `weather.py` en `jg_plugin_conversational`:**
   - Implementado el esquema Pydantic `WeatherArgs` con validación estricta de nombres geográficos y bloqueo proactivo anti-SSRF (URLs, IPs y comandos).
   - Implementada la función `get_weather_fn` con soporte dual: consulta a Azure Maps Weather API (cuando existe `AZURE_MAPS_KEY`) y simulación determinista para entornos locales y CI/CD sin credenciales.
   - Definida la factoría `create_weather_tool()` bajo el contrato `AgentTool` con `read_only=True`, `risk_level=RiskLevel.LOW`, `idempotent=True` y `makes_http_requests=True`.
2. **Integración en `ConversationalPlugin`:**
   - Registrada la herramienta `get_weather` en `register_tools()` e incorporado el tag `"weather"` en `get_plugin_metadata()`.
3. **Tests Autónomos en el Plugin:**
   - Creado `plugins/jg_plugin_conversational/tests/test_weather_tool.py` con 8 casos de prueba (validación anti-SSRF, contrato `AgentTool`, simulación determinista, mocks de Azure Maps y fallback de red).
4. **Calidad y Verificación:**
   - La suite completa de 259 tests (Core + Plugins) pasó con 100% de éxito en `./scripts/check.sh` con verificación estricta de formato (`ruff`) y tipos (`mypy`).
5. **Documentación:**
   - Generación del cuarteto documental en `docs/issues/ISSUE-F09-T02-*` y actualización del Roadmap en `README.md`.
