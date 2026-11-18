# [ISSUE-05] [jg_agente] fix(llm): Prohibir fallback automático a MockChatModel ante proveedor desconocido o entorno de producción

- **ID Maestro QA:** `ISSUE-05`
- **Proyecto Destino:** `javiergalvez-ia/jg_agente`
- **Asignado a:** `cabocom` / Javier Gálvez (`assignee_ids: [553306]`)
- **Milestone:** `QA & Anti-Fallback Hardening (Nov-Dic 2026)`
- **Labels:** `qa-audit, priority::blocker, anti-fallback, security`
- **GitLab Issue Remoto:** [jg_agente#86](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/86)

---

- **Severidad y Categoría:** `Blocker` | `Anti-Fallback IA` / `Seguridad`
- **Consenso de Auditores:** Detectado por: `argon`, `claude-sonnet`, `flash-3.8`, `hydrogen` (Unánime 4/4)
- **Evidencia Exacta:**
  - `jg_agente/app/core/llm.py:58, 72-76`
  - `jg_agente/app/core/config.py:193-196, 253-270`
  - `jg_agente/app/nodes/reason_intent_resolver.py:100-105`
  ```python
  # jg_agente/app/core/llm.py:72-76
  logger.warning(
      "Proveedor LLM desconocido '%s'. Se usará MockChatModel por defecto.",
      chosen_provider,
  )
  return MockChatModel(**kwargs)
  ```
- **Solución Técnica Propuesta:**
  1. En `get_chat_model()` (`jg_agente/app/core/llm.py:72-76`), lanzar `ValueError(f"Proveedor LLM no soportado: '{chosen_provider}'")` (*Fail-Loud*) en lugar de instanciar `MockChatModel`.
  2. Si `chosen_provider in ("mock", "fake", "test")` y `cfg.ENV.lower() in ("production", "prod")`, lanzar `RuntimeError("MockChatModel está terminantemente prohibido en entorno de producción")`.
  3. En `reason_intent_resolver.py:100-105`, reemplazar la inspección por substring de `model.__class__.__name__` por `not isinstance(model, MockChatModel)`.
- **Criterios de Aceptación (Checklist verificable):**
  - [ ] `get_chat_model(provider="unknown_provider")` lanza `ValueError`.
  - [ ] Con `ENV=production` y `LLM_PROVIDER=mock`, el arranque o `get_chat_model()` lanza `RuntimeError`.
  - [ ] Suite completa `pytest` en `jg_agente` actualizada y pasando al 100%.
