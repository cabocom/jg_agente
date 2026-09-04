# Walkthrough: ISSUE-F04-T03 — Implementación de PluginManager con autodiscovery

> **Issue ID:** ISSUE-F04-T03  
> **Fase:** FASE 04 (CapabilityRegistry y Sistema de Plugins Core)  
> **Prioridad:** High  
> **Complejidad:** M  

---

## 1. Resumen de Cambios

1. **`app/core/plugin_manager.py`:**
   - Excepciones: `PluginLoadError` y `PluginDependencyError`.
   - Clase `PluginManager`:
     - `discover_entrypoints()`: Descubrimiento de paquetes instalados vía `importlib.metadata.entry_points(group="jg_agente.plugins")`.
     - `discover_local_plugins()`: Descubrimiento dinámico en carpetas locales buscando `PLUGIN_CLASS` o subclases de `BasePlugin` con `pkgutil`.
     - `load_plugins()`: Carga, instanciación, ordenamiento topológico y registro en `CapabilityRegistry`.
     - `_resolve_dependencies_and_order()`: Algoritmo de Kahn para validar dependencias y ordenar el arranque.
     - `startup()`, `shutdown()`, `health_check()` y soporte de gestor de contexto asíncrono.
2. **`app/core/__init__.py`:**
   - Exportación de `PluginManager`, `PluginLoadError`, `PluginDependencyError`.
3. **`tests/test_plugin_manager.py`:**
   - 9 casos de prueba cubriendo:
     - Registro manual e integración con `CapabilityRegistry`.
     - Validación de tipos contra `PluginLoadError`.
     - Detección de dependencia ausente (`PluginDependencyError`).
     - Detección de dependencia circular (`PluginDependencyError`).
     - Orden de ejecución en ciclo de vida (startup en orden de dependencias, shutdown inverso).
     - Agregación de salud (`health_check`).
     - Descubrimiento vía entry points simulados.
     - Descubrimiento local en carpeta temporal con `plugin.py` y `PLUGIN_CLASS`.
4. **Documentación:**
   - Actualizado `docs/plugins.md` con la Sección 6.
   - Actualizado `README.md` y `PROJECT_CONTEXT.md`.

---

## 2. Validación y Pruebas

```bash
$ ./scripts/check.sh
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
35 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 35 source files

3️⃣  [Pytest] Ejecución de suite de tests...
116 passed in 0.79s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```
