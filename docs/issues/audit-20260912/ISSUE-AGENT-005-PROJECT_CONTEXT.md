# Contexto de Proyecto: [ISSUE-AGENT-005] Fallback offline y resolución de tests en NewsTool

## 1. Identificación y Estado
- **Issue ID:** ISSUE-AGENT-005
- **GitLab Item:** #46 (jg_agente)
- **Vínculo Auditoría:** AGENT-005
- **Fase:** Fase Post-Auditoría (Implementación de Hallazgos Codex)
- **Prioridad:** Low / Resilience
- **Complejidad Estimada:** S
- **Estado:** Implementado / Verificado

## 2. Alineación Arquitectónica
En la auditoría técnica independiente (hallazgo AGENT-005), se constató que la herramienta `NewsTool` (`plugins/jg_plugin_conversational/news.py`), responsable de consultar titulares RSS oficiales de Europa Press y conmutar a simulación determinista en caso de contingencia, presentaba un acoplamiento rígido con la resolución DNS durante la fase de validación SSRF (`ssrf_validator.validate_url()`).

En entornos sin conexión a Internet, redes aisladas o contenedores CI/CD sin acceso a DNS externos, `socket.getaddrinfo` fallaba con `socket.gaierror`. El validador SSRF devolvía `(False, "Fallo en resolución DNS: ...")`, lo que provocaba que `news.py` elevara inmediatamente una excepción no capturada `SSRFValidationError` en lugar de activar el fallback simulado declarado en el contrato de la herramienta. Además, esto rompía los tests unitarios donde se mockeaba `httpx.Client` pero no la resolución de nombres previa.

Para solucionar este defecto preservando la seguridad estricta y garantizando la resiliencia offline:
1. **Diferenciación entre Ausencia de DNS y Violación Real de SSRF:**
   - Si `validate_url` retorna `False`, `news.py` inspecciona la causa del fallo (`reason`).
   - Si el motivo corresponde a un fallo de resolución DNS (`"resolución dns"`, `"resolver"`, `"dns"`, `"nodename nor servname"`), la herramienta registra un aviso (`logger.warning`), omite la petición HTTP y conmuta limpiamente a `_get_simulated_news(topic, limit)`, retornando un `ToolResult(success=True, metadata={"source": "simulated", ...})`.
   - Si el motivo es una violación real de la política SSRF (por ejemplo, resolución a IP privada, red loopback, metadatos de nube IMDS o esquema no permitido), se registra un error de seguridad y se eleva `SSRFValidationError`, impidiendo cualquier debilitamiento de la protección SSRF.
2. **Aislamiento en Tests Unitarios:**
   - Se adaptaron los tests de parseo XML RSS para simular la resolución DNS con una IP pública legítima, permitiendo probar la lógica de parseo XML sin requerir conectividad de red real.
   - Se crearon pruebas unitarias explícitas para el fallback offline por ausencia de DNS (`test_news_offline_dns_failure_fallback`) y para el bloqueo estricto ante violaciones reales de SSRF (`test_news_real_ssrf_violation_raises`).

## 3. Criterios de Aceptación
- `NewsTool` retorna `ToolResult(success=True, metadata={"source": "simulated"})` cuando la validación falla por ausencia de resolución DNS.
- La protección SSRF se mantiene inflexible: intentos dirigidos a IPs privadas o prohibidas elevan `SSRFValidationError`.
- La suite de tests unitarios de `jg_plugin_conversational` y del core pasan al 100% de forma determinista y sin depender de conexión a Internet.
