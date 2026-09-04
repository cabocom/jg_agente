# Walkthrough: ISSUE-F04-T01 — Definición de interfaz abstracta BasePlugin y ciclo de vida

> **Issue ID:** ISSUE-F04-T01  
> **Fase:** FASE 04 (CapabilityRegistry y Sistema de Plugins Core)  
> **Prioridad:** Critical  
> **Complejidad:** S  

---

## 1. Resumen de Cambios

Se ha implementado el subsistema base de plugins en `app/plugins/`:

1. **`app/plugins/base.py`:**
   - `PluginMetadata`: Modelo Pydantic inmutable con validación de slugs y compatibilidad de versión.
   - `BaseEngine`: Clase base abstracta con propiedades obligatorias `name`, `engine_type` y hooks opcionales `startup()`, `shutdown()`.
   - `BasePlugin`: Clase base abstracta con métodos abstractos obligatorios:
     - `get_plugin_metadata() -> PluginMetadata`
     - `register_tools() -> list[AgentTool]`
     - `register_engines() -> dict[str, BaseEngine]`
     - Hooks extensibles `register_models()`, `startup()`, `shutdown()`, `health_check()`.
     - Soporte para protocolo de gestor de contexto asíncrono (`__aenter__`, `__aexit__`).
2. **`app/plugins/__init__.py`:**
   - Exportación limpia de `BasePlugin`, `BaseEngine`, `PluginMetadata`.
3. **`tests/test_base_plugin.py`:**
   - 7 pruebas unitarias verificando protección abstracta, validación de metadatos, registro de capacidades, hooks de ciclo de vida y context manager.
4. **Documentación:**
   - Creado `docs/plugins.md`.
   - Actualizado `docs/architecture.md` y `README.md`.

---

## 2. Validación y Pruebas

```bash
$ ./scripts/check.sh
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
31 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 31 source files

3️⃣  [Pytest] Ejecución de suite de tests...
97 passed in 0.79s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```
