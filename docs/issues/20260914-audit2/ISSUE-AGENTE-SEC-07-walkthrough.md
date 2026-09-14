# Walkthrough de Implementación - Issue [AGENTE-SEC-07]

## Resumen de Cambios

Se ha mitigado la vulnerabilidad de inclusión de entidades externas XML (XXE, CWE-611) y ataques DoS Billion Laughs en el procesamiento de feeds RSS de la herramienta `get_news`, reemplazando el parser nativo por `defusedxml`.

### Modificaciones Realizadas

1. **`jg_agente/pyproject.toml`:**
   - Añadida la dependencia `defusedxml>=0.7.1` en `[project.dependencies]`.

2. **`jg_agente/plugins/jg_plugin_conversational/news.py`:**
   - Reemplazado `import xml.etree.ElementTree as ET` por `import defusedxml.ElementTree as ET`.
   - `root = ET.fromstring(resp.content)` ahora ejecuta bajo las protecciones estrictas de `defusedxml`.

3. **`jg_agente/plugins/jg_plugin_conversational/tests/test_news_tool.py`:**
   - Añadido `test_news_xxe_payload_blocked_and_fallback`: inyecta un payload XML con `<!DOCTYPE rss [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>` y verifica que `defusedxml` impida la resolución de la entidad, conmutando ordenadamente a simulación sin fugas de datos locales.

---

## Verificación de Calidad

- **Pruebas del Plugin Conversacional:**
  ```bash
  ./jg_agente/.venv/bin/pytest jg_agente/plugins/jg_plugin_conversational
  # 24 passed in 0.56s
  ```

- **Suite Completa del Agente:**
  ```bash
  ./jg_agente/.venv/bin/pytest jg_agente/tests
  # 311 passed in 33.36s
  ```

- **Linter y Tipado Estático:**
  ```bash
  ./jg_agente/.venv/bin/ruff check jg_agente/app jg_agente/tests jg_agente/plugins
  # All checks passed!
  ./jg_agente/.venv/bin/ruff format --check jg_agente/app jg_agente/tests jg_agente/plugins
  # 106 files already formatted
  ./jg_agente/.venv/bin/mypy --config-file jg_agente/pyproject.toml jg_agente/app jg_agente/tests jg_agente/plugins
  # Success: no issues found in 106 source files
  ```
