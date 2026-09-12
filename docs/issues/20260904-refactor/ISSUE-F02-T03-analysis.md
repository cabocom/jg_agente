# Análisis Técnico: ISSUE-F02-T03 — Contrato de compensación y Rollback en AgentTool

> **Issue ID:** ISSUE-F02-T03  
> **Fase:** FASE 02 (Contratos y Modelos Core)  
> **Prioridad:** High  
> **Complejidad:** S  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

En sistemas autónomos de ejecución donde se invocan herramientas con mutaciones en el entorno (por ejemplo, arranque o parada de contenedores, cambios de configuración, mutaciones en bases de datos), la capacidad de revertir o compensar una acción ante fallos en pasos posteriores del grafo es crucial para la estabilidad operativa.

El Informe Arquitectónico 3 y `PROJECT_CONTEXT.md` establecen una semántica de compensación estricta y declarativa:
1. **Obligatoriedad:** Si una herramienta declara `reversible=True`, debe proporcionar obligatoriamente una función de compensación válida (`rollback_func`). De lo contrario, Pydantic debe lanzar un `ValidationError`.
2. **Inferencia:** Si se proporciona un `rollback_func`, el flag `reversible` se marca automáticamente como `True`.
3. **No Reversibilidad:** Si una herramienta es `reversible=False` (o carece de `rollback_func`), invocar `tool.rollback(context)` no lanza excepciones ni condicionales ocultos, sino que emite explícitamente un `ToolResult` con `error="NO_ROLLBACK_AVAILABLE"`.
4. **Resiliencia:** La invocación de `rollback_func` debe ejecutarse en un bloque seguro que mida la duración (`duration_ms`), capture posibles excepciones sin colapsar el agente y marque `rollback_executed=True` en los metadatos de auditoría.

---

## 2. Reutilización y Adaptación (Código Origen)

- Se tomó como referencia la Opción A documentada en el Informe Arquitectónico 3 (`Tool.rollback` opcional acoplado al descriptor).
- Se reutilizó el patrón de manejo de errores e inspección de resultados de `Devops60k/app/tools/base.py`.
- Se implementó el validador Pydantic V2 `@model_validator(mode="after")` para hacer cumplir la invariante de reversibilidad.

---

## 3. Decisiones de Diseño

1. **Validador de Coherencia (`validate_reversible_and_rollback`):**
   ```python
   if self.reversible and self.rollback_func is None:
       raise ValueError(
           "Las herramientas configuradas como reversibles (reversible=True) "
           "deben proporcionar obligatoriamente un 'rollback_func' válido para compensación."
       )
   if self.rollback_func is not None:
       self.reversible = True
   ```
2. **Método `rollback(rollback_context)`:**
   - Manejo de respuestas heterogéneas (`ToolResult`, `bool`, `str`, `dict`) normalizadas a `ToolResult`.
   - Control de excepciones para que errores dentro del rollback no tiren el ciclo del grafo.
   - Retorno explícito de `NO_ROLLBACK_AVAILABLE` si la herramienta no es reversible.

---

## 4. Criterios de Aceptación Verificados

- [x] Si `reversible=True` y `rollback_func=None`, se lanza `ValidationError` con mensaje descriptivo.
- [x] Invocación de `rollback(context)` devuelve `ToolResult` con estado compensado y `metadata["rollback_executed"] = True`.
- [x] Invocación sobre herramienta no reversible devuelve `ToolResult(success=False, error="NO_ROLLBACK_AVAILABLE")`.
- [x] 17 tests unitarios en `tests/test_tool_models.py` (totalizando 34 tests en suite completa).
- [x] Verificación completa con `./scripts/check.sh` pasando al 100%.
