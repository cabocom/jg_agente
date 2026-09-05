Se ha completado la implementación de **[ISSUE-F09-T03] Implementación de NewsTool en jg_plugin_conversational** en `jg_agente`.

### Resumen de Cambios:
1. **Módulo `news.py` en `jg_plugin_conversational`:**
   - Esquema de validación `NewsArgs` con filtrado estricto por regex, longitud máxima de topic y límite de elementos `1 <= limit <= 10`.
   - Implementada la función `get_news_fn` con validación previa de SSRF mediante `SSRFValidator` para mitigar accesos a redes internas o metadatos de nube (`169.254.0.0/16`).
   - Timeout de red estricto de 5 segundos con fallback a simulación determinista para entornos sin conectividad o tests locales.
   - Parseo seguro de feeds XML RSS (Europa Press) extrayendo títulos, descripciones y enlaces sanitizados.
   - Factoría `create_news_tool()` bajo el contrato canónico `AgentTool` (`read_only=True`, `risk_level=RiskLevel.LOW`, `idempotent=True`, `makes_http_requests=True`).
2. **Integración en `ConversationalPlugin`:**
   - Registro de la herramienta `get_news` junto a `get_weather` en `register_tools()`, ampliando los tags a `["conversational", "nlp", "interaction", "weather", "news"]`.
3. **Tests Unitarios en el Plugin:**
   - Creado `plugins/jg_plugin_conversational/tests/test_news_tool.py` con 7 casos de prueba cubriendo validación de esquemas, SSRF blocking, timeouts, parseo XML con mocks y registro en catálogo.
4. **Garantía de Calidad:**
   - Suite completa de tests pasando al 100% mediante `./scripts/check.sh` con verificación estricta de Ruff y MyPy.
5. **Documentación:**
   - Generación del cuarteto documental en `docs/issues/ISSUE-F09-T03-*` y actualización del roadmap del proyecto en `README.md`.
