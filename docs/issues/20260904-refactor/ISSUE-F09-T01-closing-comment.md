Se ha completado la implementación de **[ISSUE-F09-T01] Estructura del paquete jg_plugin_conversational**, inaugurando formalmente la **FASE 09: Plugin Conversacional** en `jg_agente`.

### Resumen de Cambios:
1. **Paquete `jg_plugin_conversational`:**
   - Creado en `plugins/jg_plugin_conversational/` con su propio `pyproject.toml`, preparado como paquete independiente distribuible con entry_point en el grupo `jg_agente.plugins`.
   - Exporta `ConversationalPlugin`, `PLUGIN_CLASS` y `__version__ = "0.1.0"` en `__init__.py`.
   - `ConversationalPlugin` implementa el contrato canónico `BasePlugin` (`get_plugin_metadata`, `register_tools`, `register_engines`, `startup`, `shutdown`, `health_check`).
2. **Agnosticismo y Aislamiento Estricto:**
   - Cero dependencias hacia infraestructura DevOps ni Asterisk/SIP directo, validado mediante inspección sintáctica por AST.
3. **Autodescubrimiento de Plugins y Tests:**
   - Los tests residen dentro del propio plugin en `plugins/jg_plugin_conversational/tests/test_plugin.py`.
   - `pyproject.toml` del Core y `scripts/check.sh` configurados con autodescubrimiento global (`testpaths = ["tests", "plugins"]`).
   - `PLUGINS_DIR` por defecto configurado a `"plugins"`.
4. **Verificación y Calidad:**
   - La suite completa de 251 tests (Core + Plugin) pasó con 100% de éxito en `./scripts/check.sh` con verificación estricta de tipos (`mypy`) y formato (`ruff`).
5. **Documentación:**
   - Generación del cuarteto documental en `docs/issues/ISSUE-F09-T01-*`.
