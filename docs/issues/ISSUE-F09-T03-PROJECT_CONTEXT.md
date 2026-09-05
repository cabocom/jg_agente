# Contexto del Proyecto - ISSUE-F09-T03: Implementación de NewsTool en jg_plugin_conversational

## 1. Identificación y Objetivos
- **Issue ID:** [jg_agente#35] [ISSUE-F09-T03]
- **Título:** Implementación de NewsTool en jg_plugin_conversational
- **Fase:** FASE 09 (Ecosistema de Plugins y Capacidades de Negocio)
- **Dependencias:** ISSUE-F03-T04 (SSRFValidator y mitigaciones de red), ISSUE-F09-T01 (Estructura del plugin)
- **Objetivo Principal:** Migrar y encapsular la herramienta de noticias bajo el contrato canónico `AgentTool` con filtrado seguro de temas, validación SSRF para llamadas HTTP externas, manejo estricto de timeout (5 segundos), fallback de simulación determinista y conformidad con SEC-06 (retorno de datos puros sin prompt injection).

## 2. Decisiones Arquitectónicas y Restricciones
- **Esquema Pydantic (`NewsArgs`):**
  - Validación de campos: `topic` (string alfanumérico restringido a patrones de búsqueda seguros, impidiendo inyecciones o caracteres de control) y `limit` (entero acotado entre 1 y 10).
- **Seguridad SSRF y Red:**
  - Empleo de `SSRFValidator` para validar el endpoint de noticias antes de cualquier conexión saliente, bloqueando redes privadas, loopback y link-local (169.254.0.0/16 IMDS).
  - Timeout estricto de 5 segundos para peticiones HTTP salientes con degradación elegante.
- **Parseo XML Seguro:**
  - Uso de `xml.etree.ElementTree` con sanitización de texto para extraer títulos, descripciones y enlaces de canales RSS públicos (por defecto feed Europa Press), previniendo vulnerabilidades de entidades XML.
- **Dual-mode / Fallback Determinista:**
  - Soporte de simulación temática determinista cuando no hay conexión de red o en entornos offline / CI/CD.
- **SEC-06 Data-Only Contract:**
  - El resultado `ToolResult` contiene estrictamente datos estructurados formateados (`output`) y metadatos limpios, sin incluir directivas o instrucciones que puedan confundir el razonamiento del LLM.
- **Localización de Tests:**
  - Los tests unitarios residen en `plugins/jg_plugin_conversational/tests/test_news_tool.py`, descubribles tanto localmente en el plugin como desde la suite raíz.
