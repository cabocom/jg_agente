# Contexto de Proyecto: [ISSUE-F09-T02] Implementación de WeatherTool en jg_plugin_conversational

## 1. Identificación y Metadatos
- **Issue ID:** `ISSUE-F09-T02`
- **Fase:** `FASE 09`
- **Prioridad:** `High`
- **Complejidad Estimada:** `S`
- **Dependencias:** `ISSUE-F02-T02`, `ISSUE-F09-T01`
- **Componente:** `plugins/jg_plugin_conversational/weather.py`

---

## 2. Propósito y Alcance
Esta tarea implementa la herramienta meteorológica `WeatherTool` (`get_weather`) dentro del paquete `jg_plugin_conversational`, migrándola desde la implementación legacy de `jg-ai-gateway` y adaptándola al contrato canónico `AgentTool`.

### Criterios de Aceptación
1. `WeatherTool` ejecuta consultas climáticas devolviendo un `ToolResult` estructurado con `read_only=True` y `risk_level=RiskLevel.LOW`.
2. Encapsula sus argumentos de entrada en el esquema Pydantic `WeatherArgs` con validación estricta y protección anti-SSRF (bloqueo de URLs, rangos IP y comandos).
3. Soporta modo dual: integración con Azure Maps Weather API (cuando exista `AZURE_MAPS_KEY`) y simulación determinista para desarrollo local y tests sin claves externas.
4. Se registra automáticamente a través de `ConversationalPlugin.register_tools()` en el `CapabilityRegistry`.
5. La suite de pruebas unitarias reside en `plugins/jg_plugin_conversational/tests/test_weather_tool.py`.
