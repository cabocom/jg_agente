# Walkthrough: ISSUE-F04-T02 — Implementación de CapabilityRegistry con detección estricta de conflictos

> **Issue ID:** ISSUE-F04-T02  
> **Fase:** FASE 04 (CapabilityRegistry y Sistema de Plugins Core)  
> **Prioridad:** Critical  
> **Complejidad:** M  

---

## 1. Resumen de Cambios

1. **`app/plugins/base.py`:**
   - Creadas las subclases `ObserverEngine`, `PlannerEngine`, `VerifierEngine` heredando de `BaseEngine`.
   - Exportadas en `app/plugins/__init__.py`.
2. **`app/core/registry.py`:**
   - Excepción `BootConflictError`.
   - Clase `CapabilityRegistry`:
     - Indexación única de herramientas por nombre (`register_tool`).
     - Validación estricta de roles singleton (`observer`, `planner`, `verifier`) impidiendo colisiones (`register_engine`).
     - Registro en cascada de plugins (`register_plugin`).
     - Filtros de herramientas por categoría y `RiskLevel`.
     - Exportación a herramientas LangChain (`get_langchain_tools`).
     - Resumen estructurado para observabilidad (`get_capabilities_summary`).
3. **`app/core/__init__.py`:**
   - Exportación de `CapabilityRegistry` y `BootConflictError`.
4. **`tests/test_capability_registry.py`:**
   - 10 casos de prueba validando indexación de tools, conflicto de herramientas duplicadas, conflicto estricto de dos `PlannerEngine` (criterio de aceptación), conflicto de dos `ObserverEngine`/`VerifierEngine`, coexistencia de motores no singleton y registro en cascada de plugins.
5. **Documentación:**
   - Actualizado `docs/plugins.md` con la Sección 5.
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
33 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 33 source files

3️⃣  [Pytest] Ejecución de suite de tests...
107 passed in 0.87s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```
