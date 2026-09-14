# Análisis Técnico - Issue [AGENTE-SEC-07]

**Issue:** [jg_agente#63](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/63)  
**Título:** [AGENTE-SEC-07] Vulnerabilidad XXE en Parser de Feeds RSS de news_tool  
**Severidad:** 🟡 MEDIO  
**CWE:** CWE-611 (Improper Restriction of XML External Entity Reference)  
**Ubicación:** `jg_agente/plugins/jg_plugin_conversational/news.py:176`  

---

## 1. Contexto y Causa Raíz

La herramienta `get_news` del plugin conversacional (`jg_plugin_conversational`) consulta feeds RSS externos (por defecto de Europa Press) y procesa el cuerpo de la respuesta HTTP para extraer titulares, enlaces y descripciones.

### Vulnerabilidad Identificada

El código utilizaba la librería estándar `xml.etree.ElementTree`:
```python
import xml.etree.ElementTree as ET
...
root = ET.fromstring(resp.content)
```

Por diseño, los parsers XML estándar de Python no deshabilitan las referencias a entidades externas (XXE) ni las declaraciones DTD personalizadas por defecto, exponiendo el sistema a:
1. **Inyección de Entidades Externas (XXE):** Si un atacante compromete la fuente RSS o logra redirigir la petición hacia un feed malicioso que contenga `<!ENTITY xxe SYSTEM "file:///etc/passwd">`, el parser podría intentar resolver la entidad y exponer archivos locales confidenciales del contenedor.
2. **Denegación de Servicio (Billion Laughs / Entity Expansion):** Un archivo XML con anidamiento recursivo de entidades (`<!ENTITY lol ...>`) puede provocar agotamiento exponencial de memoria RAM y bloqueo de la CPU en el worker del agente.

---

## 2. Impacto de Seguridad

- **CWE-611:** Divulgación no autorizada de archivos del host/contenedor o denegación de servicio por agotamiento de recursos ante respuestas XML no confiables.

---

## 3. Solución Implementada

1. **Adición de Dependencia `defusedxml`:**
   - Incorporado `defusedxml>=0.7.1` en `pyproject.toml`.
   - La librería `defusedxml` reemplaza el parser nativo de `xml.etree.ElementTree` neutralizando de forma automática e intrínseca cualquier intento de expansión de entidades DTD o inclusión de recursos externos.

2. **Refactorización del Parser en `news.py`:**
   - Sustituido `import xml.etree.ElementTree as ET` por `import defusedxml.ElementTree as ET`.
   - `defusedxml.ElementTree.fromstring(resp.content)` rechaza cualquier documento con entidades externas o DTD lanzando excepciones seguras (`EntitiesForbidden`, `DTDForbidden`), las cuales son capturadas por el manejador de fallos de la herramienta, conmutando ordenadamente a la simulación segura sin exponer información interna.

3. **Prueba Automatizada Anti-XXE:**
   - En `jg_agente/plugins/jg_plugin_conversational/tests/test_news_tool.py`, se añadió `test_news_xxe_payload_blocked_and_fallback`: simula un feed con payload `<!ENTITY xxe SYSTEM "file:///etc/passwd">` y valida que `defusedxml` neutralice la amenaza, impidiendo la lectura de archivos sensibles y garantizando el fallback seguro.
