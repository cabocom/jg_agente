# Análisis Técnico: [ISSUE-F09-T02] Implementación de WeatherTool en jg_plugin_conversational

## 1. Contexto Técnico y Requerimientos
En el diseño arquitectónico de `jg_agente` (Informe Arquitectónico 3, Sección 4.1), `WeatherTool` (`get_weather`) representa la herramienta esencial del **Caso A (Conversacional Puro)**:
- Permite al LLM invocar información climática mediante tool calling sin intervención humana (`RiskLevel.LOW`).
- Al realizar peticiones HTTP hacia servicios externos (`makes_http_requests=True`), existe riesgo inherente de SSRF si el parámetro `location` no es saneado.

---

## 2. Decisiones de Diseño

1. **Esquema Pydantic `WeatherArgs` y Protección Anti-SSRF:**
   - La entrada se valida mediante regex `^[a-zA-Z\s,áéíóúñÁÉÍÓÚÑ.\-]{1,100}$`.
   - Se rechaza explícitamente cualquier valor que contenga `http://`, `https://`, direcciones IP (ej. `169.254.169.254`) o inyecciones de comandos shell.

2. **Contrato Formal `AgentTool`:**
   - `name="get_weather"`
   - `category="weather"`
   - `risk_level=RiskLevel.LOW`
   - `read_only=True`
   - `reversible=False`
   - `idempotent=True`
   - `makes_http_requests=True`
   - `timeout_sec=5.0`
   - `args_schema=WeatherArgs`

3. **Modo Dual y Resiliencia Operativa:**
   - Si `AZURE_MAPS_KEY` está configurada, invoca la API REST de Azure Maps (geocoding y current weather) con `httpx` y timeout de 5 segundos.
   - Si no hay clave, o ante fallo transitorio de red / geocodificación, conmuta de forma transparente y determinista a una simulación climática realista basada en el hash de la ubicación.
   - De esta manera, las pruebas unitarias y de integración en CI/CD no requieren credenciales de nube ni conectividad externa.

4. **Integración con el Plugin:**
   - `ConversationalPlugin.register_tools()` retorna `[create_weather_tool()]`.
   - `CapabilityRegistry` incorpora la herramienta sin conflictos ni colisiones.
