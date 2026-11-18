# [ISSUE-09] [jg_agente] fix(runtime): Corregir comparación de PolicyDecision en api/tools.py, bloqueo time.sleep en checkpointer y catches silenciosos en sanitizer.py

- **ID Maestro QA:** `ISSUE-09`
- **Proyecto Destino:** `javiergalvez-ia/jg_agente`
- **Asignado a:** `cabocom` / Javier Gálvez (`assignee_ids: [553306]`)
- **Milestone:** `QA & Anti-Fallback Hardening (Nov-Dic 2026)`
- **Labels:** `qa-audit, priority::high, security, bug`
- **GitLab Issue Remoto:** [jg_agente#90](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/90)

---

- **Severidad y Categoría:** `Major` | `Fiabilidad-Bug` / `Seguridad`
- **Consenso de Auditores:** Detectado por: `argon` (`api/tools.py`, `checkpointer.py`, `registration_store.py`), `claude-sonnet` y `hydrogen` (`sanitizer.py`)
- **Evidencia Exacta:**
  - `jg_agente/app/api/tools.py:94-97` (`result.metadata.get("security_decision") == "require_approval"` vs `PolicyDecision.REQUIRE_HUMAN_APPROVAL.value == "require_human_approval"`)
  - `jg_agente/app/core/checkpointer.py:172` (`time.sleep(wait_seconds)`)
  - `jg_agente/app/security/sanitizer.py:50, 77, 87, 94` (`except Exception: pass`)
  - `jg_agente/app/core/registration_store.py:68-80` (posible fuga de file descriptor `fd` si falla antes de `with open(fd, ...)`)
- **Solución Técnica Propuesta:**
  1. En `app/api/tools.py:96`, comparar contra `PolicyDecision.REQUIRE_HUMAN_APPROVAL.value`.
  2. En `app/core/checkpointer.py`, proporcionar inicialización asíncrona con `await asyncio.sleep(wait_seconds)` cuando se invoca desde `lifespan`.
  3. En `app/security/sanitizer.py:50, 77, 87, 94`, capturar `(OSError, ValueError)` registrando un `logger.debug/warning` o rechazando la ruta si es irresoluble.
  4. En `app/core/registration_store.py:68-80`, asegurar el cierre de `fd` en caso de error previo a `with open(fd, ...)`.
- **Criterios de Aceptación (Checklist verificable):**
  - [ ] `ruff check .` y `pytest` en `jg_agente` pasan al 100%.
