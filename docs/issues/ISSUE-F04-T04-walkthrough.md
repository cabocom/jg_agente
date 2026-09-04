# Walkthrough: ISSUE-F04-T04 — Validación en boot del agente contra CapabilityRegistry

> **Issue ID:** ISSUE-F04-T04  
> **Fase:** FASE 04 (CapabilityRegistry y Sistema de Plugins Core)  
> **Prioridad:** High  
> **Complejidad:** S  

---

## 1. Resumen de Cambios

1. **`app/core/config.py`:**
   - Nuevos campos en `Settings` para requerimientos de arranque: `PLUGINS_DIR`, `REQUIRED_PLUGINS`, `REQUIRED_TOOLS`, `REQUIRE_PLANNER`, `REQUIRE_OBSERVER`, `REQUIRE_VERIFIER`.
2. **`app/core/boot.py`:**
   - `BootIntegrityError`: Excepción canónica para fallos de integridad en arranque.
   - `validate_boot_capabilities()`: Función de validación contra capacidades requeridas y consistencia de herramientas.
   - `init_agent_capabilities()`: Orquestador de arranque que inicializa el registro, carga plugins y valida la integridad.
3. **`app/core/__init__.py`:**
   - Exportación de `BootIntegrityError`, `validate_boot_capabilities`, `init_agent_capabilities`.
4. **`app/main.py`:**
   - Modificado el ciclo `lifespan` para ejecutar `init_agent_capabilities()`.
   - Incorporado el endpoint `GET /capabilities`.
5. **`tests/test_boot_validation.py`:**
   - 11 casos de prueba verificando validación de plugins, herramientas y motores, aborto ante componentes ausentes, aborto ante colisiones, endpoint `/capabilities` y fallo en el ciclo de vida de FastAPI.
6. **Documentación:**
   - Actualizado `docs/plugins.md` (Sección 7).
   - Actualizado `README.md` (Fase 04 100% completada) y `PROJECT_CONTEXT.md` (v2.9.0).

---

## 2. Validación y Pruebas

```bash
$ ./scripts/check.sh
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
37 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 37 source files

3️⃣  [Pytest] Ejecución de suite de tests...
127 passed in 0.76s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```
