# [REFACTOR-v2.0] Refactorización Estructural SOLID del Motor Core (`jg_agente`)

- **Estado:** Abierto / Planificado
- **Fecha:** 2026-11-09
- **Proyecto:** `jg_agente`
- **GitLab Issue:** [jg_agente#82](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/82)
- **Asignado a:** Javier Gálvez (`@cabocom`)
- **Documento Maestro:** [`docs/refactor.md`](../../../docs/refactor.md)

---

## 1. Contexto y Objetivo (Arquitectura v2.0 SOLID)

Este issue planifica la refactorización estructural v2.0 de `jg_agente` para cumplir las reglas de programación estructurada y principios **SOLID** definidos en `AGENTS.md` (Sección 8) y `docs/refactor.md` (límite máximo de **300 LOC por módulo/clase** y **40 LOC por función**).

## 2. Diagnóstico Real de Ficheros Monolíticos (`>300 LOC`)

`jg_agente` cuenta con 14.222 LOC de producción y una suite de 13.206 LOC de tests. Presenta **19 ficheros por encima de 300 líneas**, destacando:
1. `app/api/executions.py` (**1.452 LOC**, 15 funciones)
2. `app/security/ssrf.py` (**838 LOC**, 28 funciones)
3. `app/core/graph.py` (**730 LOC**, 31 funciones)
4. `app/security/guard.py` (**626 LOC**, 11 funciones)
5. `app/nodes/reason.py` (**609 LOC**, 7 funciones)
6. `app/prompts/manager.py` (**539 LOC**)
7. `app/core/registration.py` (**534 LOC**)
8. `app/core/llm.py` (**517 LOC**)
9. `app/security/audit.py` (**458 LOC**) y `app/nodes/execute.py` (**458 LOC**)

## 3. Plan de Refactorización Estructural (Cero Roturas)

- **Fase 1 (`app/api/executions.py` -> Servicios de Orquestación) [COMPLETADA]:**
  - Router `app/api/executions.py` reducido de **1.451 LOC a 284 LOC** (controlador HTTP delgado).
  - Lógica de negocio segmentada en `app/services/`:
    - `execution_orchestrator.py` (269 LOC)
    - `hitl_resume_service.py` (227 LOC)
    - `hitl_interrupt_service.py` (153 LOC)
    - `execution_persistence_service.py` (238 LOC)
    - `execution_query_service.py` (257 LOC)
    - `execution_notification_service.py` (177 LOC)
    - `background_execution_service.py` (76 LOC)
  - Re-exportación completa de fachadas públicas y retrocompatibilidad 100% con tests existentes.
- **Fase 2 (`app/security/` -> Submódulos Especializados) [COMPLETADA]:**
  - Descomposición de `ssrf.py` (de 838 LOC a 61 LOC) en `dns_pinning.py` (188 LOC), `ip_policy.py` (71 LOC), `safe_http_client.py` (103 LOC), `ssrf_url_inspector.py` (142 LOC) y `ssrf_validator.py` (292 LOC).
  - Descomposición de `guard.py` (de 626 LOC a 199 LOC) en `guard_policy.py` (192 LOC), `sanitizer.py` (196 LOC) y `tool_executor.py` (100 LOC).
  - Descomposición de `audit.py` (de 458 LOC a 278 LOC) en `audit_builders.py` (227 LOC) y `audit_persistence.py` (94 LOC).
  - Preservación íntegra de singletons thread-safe (`get_security_guard`, `get_ssrf_validator`, `get_security_audit_logger`) y retrocompatibilidad total (447/447 tests pasando).
- **Fase 3 (`app/core/` y `app/nodes/`):**
  - Separar constructores del grafo en `app/core/graph_builder.py` y modularizar `reason.py`, `execute.py`, `llm.py` y `registration.py`.

## 4. Estimación con Gemini Flash y Criterios de Aceptación

- **Esfuerzo estimado:** 5 – 6 sesiones (~3,0 M – 4,0 M tokens Gemini Flash, ~2 – 2,5 horas).
- **Criterios de cierre:**
  - [ ] Router `executions.py` y módulos principales bajo el umbral de 300 LOC.
  - [ ] 100% de la suite de tests en verde (`pytest`) y linter limpio (`ruff check .`).
