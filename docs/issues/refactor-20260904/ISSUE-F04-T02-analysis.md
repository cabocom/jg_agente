# Análisis Técnico: ISSUE-F04-T02 — Implementación de CapabilityRegistry con detección estricta de conflictos

> **Issue ID:** ISSUE-F04-T02  
> **Fase:** FASE 04 (CapabilityRegistry y Sistema de Plugins Core)  
> **Prioridad:** Critical  
> **Complejidad:** M  
> **Estado:** Implementado y Verificado  

---

## 1. Contexto y Objetivos

Para que `jg_agente` sea extensible pero determinista y seguro en producción, el catálogo de capacidades debe indexarse centralmente durante el arranque sin permitir sobreescrituras accidentales ni colisiones de nombres o roles.

El objetivo de este issue es:
1. Desarrollar `CapabilityRegistry` en `app/core/registry.py`.
2. Definir la excepción `BootConflictError` lanzada de forma inmediata ante cualquier colisión.
3. Indexar herramientas (`AgentTool`) por `name` único; rechazar duplicados.
4. Definir las clases base `ObserverEngine`, `PlannerEngine` y `VerifierEngine` en `app/plugins/base.py`.
5. Asegurar la regla de unicidad para motores cognitivos singleton (`observer`, `planner`, `verifier`), garantizando que intentar registrar dos motores para el mismo rol (e.g. dos `PlannerEngine`) aborte el arranque con `BootConflictError`.
6. Permitir la coexistencia de motores no singleton (e.g. `discovery`) siempre que sus nombres sean únicos.
7. Soportar el registro en cascada de plugins mediante `register_plugin(plugin: BasePlugin)`.
8. Generar resúmenes estructurados para observabilidad y el endpoint `GET /capabilities`.

---

## 2. Reutilización y Adaptación (Código Origen)

- En `jg-ai-gateway/app/core/registry.py`, `ToolRegistry` era un diccionario básico de callables sin validación de colisiones ni tipado estricto.
- En `Devops60k/app/tools/registry.py`, `ToolRegistry` sobrescribía silenciosamente las herramientas (`logger.debug("Sobrescribiendo...")`).
- En `jg_agente`, se implementó una **política estricta de fallo en boot** (`fail-fast`): cualquier duplicado o conflicto de motor cognitivo aborta el arranque inmediatamente para evitar comportamientos impredecibles o vulnerabilidades.

---

## 3. Decisiones de Diseño

1. **Catálogo de Roles Singleton:**
   - Se estableció `SINGLETON_ENGINE_TYPES = frozenset({"observer", "planner", "verifier"})`.
   - Si un motor pertenece a uno de estos roles y ya existe uno registrado (incluso con distinto nombre), se lanza `BootConflictError`.
2. **Indexación de Herramientas:**
   - Indexadas por `tool.name`. Intentar registrar una segunda herramienta con el mismo nombre lanza `BootConflictError`.
   - Consulta con filtros funcionales (`category`) y de seguridad (`max_risk`).
   - Exportación nativa a LangChain (`as_langchain_tool()`).
3. **Registro en Cascada:**
   - `register_plugin()` registra automáticamente modelos, herramientas y motores provistos por un `BasePlugin`. Si cualquier componente colisiona, la operación falla atómicamente.

---

## 4. Criterios de Aceptación Verificados

- [x] Intento de registrar dos `PlannerEngine` distintos lanza `BootConflictError` explícito impidiendo el arranque.
- [x] Herramientas se indexan por nombre único; nombres duplicados lanzan `BootConflictError`.
- [x] Regla de unicidad validada para `ObserverEngine` y `VerifierEngine`.
- [x] Motores no singleton admiten múltiples instancias con nombres distintos.
- [x] 107 tests pasando con éxito (100% verde en Ruff, MyPy estricto y Pytest).
