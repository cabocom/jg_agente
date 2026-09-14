### ✅ Resolución y Cierre de Issue [AGENTE-SEC-07]

**Issue:** [jg_agente#63](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/63)
**Título:** [AGENTE-SEC-07] Vulnerabilidad XXE en Parser de Feeds RSS de news_tool
**Severidad:** 🟡 MEDIO
**CWE:** CWE-611 (Improper Restriction of XML External Entity Reference)

---

#### 1. Causa Raíz Identificada
En `jg_agente/plugins/jg_plugin_conversational/news.py:176`, el procesamiento de feeds RSS externos utilizaba `xml.etree.ElementTree.fromstring(resp.content)`. Al ser el parser estándar de Python, no restringe la resolución de entidades externas (XXE) ni las declaraciones DTD personalizadas, posibilitando ataques de divulgación de archivos del host (`file:///etc/passwd`) o denegación de servicio por expansión exponencial de entidades (Billion Laughs).

#### 2. Cambios Implementados
- **Incorporación de `defusedxml`:**
  - Se agregó `defusedxml>=0.7.1` a las dependencias formales en `pyproject.toml` e instaló en el entorno virtual.
- **Endurecimiento del Parser en `news.py`:**
  - Se sustituyó `xml.etree.ElementTree` por `defusedxml.ElementTree as ET`.
  - El método `ET.fromstring(...)` rechaza de manera determinista cualquier payload XML que contenga DTDs o entidades externas.
- **Pruebas Automatizadas Anti-XXE:**
  - Se implementó `test_news_xxe_payload_blocked_and_fallback` en `test_news_tool.py`, validando el rechazo efectivo de entidades externas y la conmutación segura hacia la simulación sin fuga de información.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Formato y análisis estático 100% limpios sin advertencias (`106 source files`).
- **Pytest:** 10/10 tests pasando en `test_news_tool.py` y 24/24 en el plugin conversacional.
- **check.sh Global:** Verificación integral de `jg_agente`, `jg_dashboard` y Selenium E2E superada al 100%.
