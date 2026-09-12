# Análisis Técnico: ISSUE-F02-T02 — Contrato definitivo de AgentTool y ToolResult

> **Issue ID:** ISSUE-F02-T02  
> **Fase:** FASE 02 (Contratos y Modelos Core)  
> **Prioridad:** Critical  
> **Complejidad:** S  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

En el diseño del Execution Plane (`jg_agente`), las herramientas no son clases abstractas complejas ni interfaces monolíticas con dependencias directas a frameworks de orquestación. Son **descriptores de datos ejecutables** (`AgentTool`) que encapsulan la metadata necesaria para:
1. El **LLM (Function Calling)**: a través de `name`, `description` y `args_schema` (subclase de `pydantic.BaseModel`).
2. La **Capa de Seguridad (`SecurityGuard`)**: mediante `risk_level` (`RiskLevel`), `required_permissions`, `read_only` y `makes_http_requests`.
3. El **Motor de Ciclo Cognitivo**: mediante `tool_type` (`ToolType`), `idempotent` y `timeout_sec`.
4. El **Motor de Recuperación y Compensación**: mediante `reversible`, `rollback_func` y `ToolResult.rollback_context`.

Este issue formaliza el contrato estricto de `AgentTool` y `ToolResult` como parte de los modelos troncales del Core.

---

## 2. Reutilización y Adaptación (Código Origen)

- Se tomó como base `DevopsTool` y `ToolResult` de `Devops60k/app/tools/base.py` y `Devops60k/app/models/state.py`.
- Se desacopló de conceptos específicos de DevOps eliminando dependencias directas a `Incident` o decisiones locales fijas.
- Se implementaron los 5 campos booleanos de efectos secundarios acordados en el Informe Arquitectónico 3 (`read_only`, `reversible`, `idempotent`, `makes_http_requests`, `timeout_sec`).
- Se incorporó soporte nativo para interoperabilidad con LangChain (`as_langchain_tool()`), permitiendo enlazar cualquier `AgentTool` directamente con `llm.bind_tools()`.

---

## 3. Decisiones de Diseño

1. **Validación de Invocables y Esquemas:**
   - Validadores `@field_validator("func")` y `@field_validator("rollback_func")` comprueban que los campos ejecutables sean `callable`.
   - Validador `@field_validator("args_schema")` exige que el esquema sea una subclase de `BaseModel` cuando se proporciona.
   - Validador `@model_validator(mode="after")` garantiza coherencia: si se define `rollback_func`, el flag `reversible` pasa a `True` automáticamente.

2. **Estructura de `ToolResult`:**
   - Contiene `success: bool`, `output: Any`, `error: str | None`, `duration_ms: float`, `metadata: dict[str, Any]` y `rollback_context: dict[str, Any] | None`.
   - Sobrescribe `__str__` para representar el resultado textual o error ante invocaciones de herramientas desde el modelo de lenguaje.

3. **Ubicación:**
   - Implementado en `app/models/tools.py`.
   - Exportado desde `app/models/__init__.py`.

---

## 4. Criterios de Aceptación Verificados

- [x] Clase `AgentTool` valida campos obligatorios (`args_schema`, `func`, `risk_level`, `reversible`, `name`, `description`).
- [x] Clase `ToolResult` encapsula salida, estado de error y `rollback_context`.
- [x] Conversión funcional a LangChain `StructuredTool` validada.
- [x] 14 tests unitarios específicos pasando en `tests/test_tool_models.py` (totalizando 31 tests passing sin warnings).
