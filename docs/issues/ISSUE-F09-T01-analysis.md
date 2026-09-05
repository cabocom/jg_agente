# Análisis Técnico: [ISSUE-F09-T01] Estructura del paquete jg_plugin_conversational

## 1. Contexto Técnico y Requerimientos
El pilar de extensibilidad de `jg_agente` impone que toda funcionalidad especializada de dominio se suministre exclusivamente como plugins dinámicos. En la Fase 04 se estableció el contrato `BasePlugin`, el registro estricto `CapabilityRegistry` y el gestor de carga `PluginManager`.

El paquete `jg_plugin_conversational` representa el primer plugin del ecosistema:
- Debe actuar como paquete independiente estándar en Python.
- Debe registrar metadatos canónicos `PluginMetadata` (nombre `"conversational"`, versión `"0.1.0"`, tags).
- Debe responder limpiamente a los hooks de ciclo de vida (`startup`, `shutdown`, `health_check`).
- Debe ubicar sus tests en `plugins/jg_plugin_conversational/tests/`, con autodescubrimiento tanto local como agregado desde la raíz de `jg_agente`.

---

## 2. Decisiones de Diseño

1. **Estructura del Paquete:**
   Se utiliza el layout canónico testeado por `PluginManager.discover_local_plugins`:
   - `plugins/jg_plugin_conversational/__init__.py`
   - `plugins/jg_plugin_conversational/plugin.py`
   - `plugins/jg_plugin_conversational/pyproject.toml`
   - `plugins/jg_plugin_conversational/tests/test_plugin.py`

2. **Entry Points vs. Descubrimiento Local:**
   El paquete soporta ambos mecanismos:
   - Declaración de entry_point en `[project.entry-points."jg_agente.plugins"]` para cuando se instale como dependencia distribuible.
   - Ubicación en `plugins/` para escaneo y carga dinámica local en desarrollo y contenedores sin necesidad de reinstalación vía pip.

3. **Agnosticismo y Aislamiento Estricto:**
   Validado mediante análisis de AST sintáctico en `tests/test_plugin.py` para asegurar que no existan dependencias indeseadas hacia DevOps (`docker`, `k8s`) ni Asterisk (`ari`, `pjsip`).

4. **Autodescubrimiento de Pruebas:**
   `testpaths = ["tests", "plugins"]` en `pyproject.toml` del Core permite que `pytest` agregue automáticamente las suites de todos los plugins existentes.
