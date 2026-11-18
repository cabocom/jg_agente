# [ISSUE-10] [jg_agente] refactor(dry): Eliminar duplicación de contratos Pydantic, clases base de plugins y primitivas HMAC importándolos desde jg_agente_sdk

- **ID Maestro QA:** `ISSUE-10`
- **Proyecto Destino:** `javiergalvez-ia/jg_agente`
- **Asignado a:** `cabocom` / Javier Gálvez (`assignee_ids: [553306]`)
- **Milestone:** `QA & Anti-Fallback Hardening (Nov-Dic 2026)`
- **Labels:** `qa-audit, priority::critical, dry, sonar-debt`
- **GitLab Issue Remoto:** [jg_agente#91](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/91)

---

- **Severidad y Categoría:** `Critical` | `DRY-Duplicación`
- **Consenso de Auditores:** Detectado por: `argon`, `claude-sonnet`, `flash-3.8`, `hydrogen` (Unánime 4/4)
- **Evidencia Exacta:**
  - `jg_agente/app/plugins/base.py:19-205` vs `jg_agente_sdk/jg_sdk/contracts_plugins.py:22-206`
  - `jg_agente/app/models/tools.py:28-193` (165 líneas de fallback `except ImportError`)
  - `jg_agente/app/models/io.py:46-179`, `app/models/enums.py:13-94`, `app/models/records.py:19-155`
  - `jg_agente/app/security/auth.py:74-120` vs `jg_agente_sdk/jg_sdk/auth.py:25-67`
  - `jg_agente/app/security/ip_policy.py:13-71` y `ssrf_url_inspector.py:82-105` vs `jg_agente_sdk/jg_sdk/security/ssrf.py:21-96`
- **Solución Técnica Propuesta:**
  1. Reemplazar las reimplementaciones locales en `jg_agente/app/plugins/base.py`, `app/models/tools.py`, `app/security/ip_policy.py` y `app/security/auth.py` por importaciones y re-exportaciones (`__all__`) directas desde `jg_sdk` (manteniendo compatibilidad hacia atrás según Regla 8.3 de `AGENTS.md`).
- **Criterios de Aceptación (Checklist verificable):**
  - [ ] `tests/test_contracts_drift.py` y los 422 tests de `jg_agente` pasan al 100% sin código duplicado.
