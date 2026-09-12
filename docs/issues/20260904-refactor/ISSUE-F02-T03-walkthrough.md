# Walkthrough: ISSUE-F02-T03 — Contrato de compensación y Rollback en AgentTool

> **Estado:** COMPLETADO Y VALIDADO  
> **Fecha:** 4 de septiembre de 2026  
> **Comandos de Verificación:** `./scripts/check.sh`  

---

## 1. Resumen de Cambios Realizados

1. **Refuerzo de Validación en AgentTool ([app/models/tools.py](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/tools.py)):**
   - Actualizado `@model_validator(mode="after")` `validate_reversible_and_rollback`:
     - Dispara `ValueError` / `ValidationError` si `reversible=True` y `rollback_func=None`.
     - Garantiza que si `rollback_func` está presente, `reversible` siempre sea `True`.

2. **Ejecución Resiliente de Rollback ([app/models/tools.py](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/app/models/tools.py)):**
   - Método `rollback(rollback_context: dict[str, Any]) -> ToolResult`:
     - Si `not self.reversible` o `self.rollback_func is None`, devuelve `ToolResult(success=False, error="NO_ROLLBACK_AVAILABLE")` sin invocar nada ni lanzar excepciones.
     - Si es reversible, ejecuta `rollback_func` de forma aislada, calcula `duration_ms`, marca `metadata["rollback_executed"] = True` y normaliza la salida.
     - Si `rollback_func` lanza una excepción no controlada, la captura y devuelve `ToolResult(success=False, error=f"Error durante la compensación: {exc}")`.

3. **Ampliación de Pruebas Unitarias ([tests/test_tool_models.py](file:///Users/javiergalvez/Documents/Code/javiergalvez-ia/jg_agente/tests/test_tool_models.py)):**
   - `test_agent_tool_reversible_true_without_rollback_func_raises_validation_error`: prueba el rechazo de Pydantic.
   - `test_agent_tool_rollback_when_no_rollback_func`: verifica el código de error `NO_ROLLBACK_AVAILABLE`.
   - `test_agent_tool_rollback_exception_handling`: comprueba el aislamiento de fallos dentro de funciones compensadoras.
   - `test_agent_tool_rollback_primitive_returns`: comprueba la normalización de retornos primitivos.

---

## 2. Evidencias de Validación

Ejecución del script unificado `./scripts/check.sh`:

```text
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
12 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 12 source files

3️⃣  [Pytest] Ejecución de suite de tests...
..................................                                       [100%]
34 passed in 0.27s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```

---

## 3. Criterios de Aceptación Cumplidos

- [x] Si `reversible=True` y `rollback_func=None`, se lanza `ValidationError`.
- [x] La invocación de `rollback` devuelve `ToolResult` con estado compensado y metadatos de ejecución.
- [x] Emisión normalizada de `NO_ROLLBACK_AVAILABLE` en herramientas no reversibles.
