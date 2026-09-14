# Contexto de Proyecto - Issue [AGENTE-SEC-07]

## Información General
- **Repositorio:** `jg_agente`
- **Issue:** [jg_agente#63](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/63)
- **Título:** [AGENTE-SEC-07] Vulnerabilidad XXE en Parser de Feeds RSS de news_tool
- **Severidad:** 🟡 MEDIO
- **CWE:** CWE-611 (Improper Restriction of XML External Entity Reference)

## Módulos y Archivos Involucrados
1. `jg_agente/pyproject.toml`:
   - Adición de `defusedxml>=0.7.1` a la sección `dependencies`.
2. `jg_agente/plugins/jg_plugin_conversational/news.py`:
   - Sustitución de `xml.etree.ElementTree` por `defusedxml.ElementTree` para el parseo endurecido de respuestas XML/RSS.
3. `jg_agente/plugins/jg_plugin_conversational/tests/test_news_tool.py`:
   - Incorporación de test unitario verificando el bloqueo de payloads maliciosos con entidades externas y DTDs.
