# [ISSUE-11] [jg_agente] refactor(solid): Segregar clases con >10 métodos públicos (CapabilityRegistry, SecurityAuditLogger, SSRFValidator), reducir funciones >40 líneas y eliminar acoplamiento services -> api

- **ID Maestro QA:** `ISSUE-11`
- **Proyecto Destino:** `javiergalvez-ia/jg_agente`
- **Asignado a:** `cabocom` / Javier Gálvez (`assignee_ids: [553306]`)
- **Milestone:** `QA & Anti-Fallback Hardening (Nov-Dic 2026)`
- **Labels:** `qa-audit, priority::high, solid, sonar-debt`
- **GitLab Issue Remoto:** [jg_agente#92](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/92)

---

- **Severidad y Categoría:** `Major` | `Complejidad-CodeSmell`
- **Consenso de Auditores:** Detectado por: `argon`, `claude-sonnet`, `flash-3.8`, `hydrogen` (Unánime 4/4)
- **Evidencia Exacta:**
  - Clases con >10 métodos públicos (Regla 8.1 de `AGENTS.md`): `jg_agente/app/core/registry.py:51-288` (`CapabilityRegistry`, 22 métodos), `jg_agente/app/security/audit.py:50-254` (`SecurityAuditLogger`, 12 métodos), `jg_agente/app/security/ssrf_validator.py:35-228` (`SSRFValidator`, 11 métodos).
  - Funciones complejas (>100 líneas / `C901 > 12`): `plan_node` (`plan.py:54`, 208L, `C901=22`), `_resolve_raw_final_response` (`conclude_response_synthesizer.py:130`, 93L, `C901=20`), `rollback_node` (`rollback.py:33`, 173L), `verify_node` (`verify.py:36`, 158L, `C901=14`), `evaluate_steps_risk` (`risk_assess_evaluator.py:94`, 143L), `verify_control_plane_auth` (`auth.py:123`, 142L).
  - Acoplamiento inverso `services -> app.api.executions`: `execution_orchestrator.py:104`, `execution_persistence_service.py:192`, `hitl_interrupt_service.py:66`, `hitl_resume_service.py:142`, `background_execution_service.py:38`.
- **Solución Técnica Propuesta:**
  1. Descomponer `CapabilityRegistry` delegando en sub-registros especializados (`ToolRegistry`, `EngineRegistry`, `PluginCatalog`) manteniendo fachadas ligeras.
  2. Extraer un servicio común de persistencia con fallback a spool para eliminar la cuadruplicación y los imports inversos hacia `app.api.executions`.
  3. Descomponer `plan_node`, `rollback_node`, `verify_node` y `_resolve_raw_final_response` en funciones auxiliares `<= 40` líneas.
- **Criterios de Aceptación (Checklist verificable):**
  - [ ] Ninguna clase de `jg_agente` supera los 10 métodos públicos ni las 300 líneas.
  - [ ] Ningún módulo bajo `app/services/` importa desde `app/api/`.

---
