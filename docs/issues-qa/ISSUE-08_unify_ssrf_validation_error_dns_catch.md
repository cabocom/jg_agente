# [ISSUE-08] [jg_agente] fix(security): Unificar SSRFValidationError con jg_agente_sdk y corregir captura DNS en SSRFValidator

- **ID Maestro QA:** `ISSUE-08`
- **Proyecto Destino:** `javiergalvez-ia/jg_agente`
- **Asignado a:** `cabocom` / Javier Gálvez (`assignee_ids: [553306]`)
- **Milestone:** `QA & Anti-Fallback Hardening (Nov-Dic 2026)`
- **Labels:** `qa-audit, priority::critical, security, bug`
- **GitLab Issue Remoto:** [jg_agente#89](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/89)

---

- **Severidad y Categoría:** `Critical` | `Fiabilidad-Bug` / `Seguridad`
- **Consenso de Auditores:** Detectado por: `argon` | Omitido por: `claude-sonnet`, `flash-3.8`, `hydrogen`
- **Evidencia Exacta:**
  - `jg_agente/app/security/ssrf_validator.py:127-131, 149-153, 168-174, 191-197`
  - `jg_agente/app/security/ip_policy.py:13`
  - `jg_agente_sdk/jg_sdk/security/ssrf.py:21, 174-177`
  ```python
  # jg_agente/app/security/ssrf_validator.py:127-131
      resolved = self.resolve_host(hostname, port)
      ok, err_msg, _ = self._check_resolved_ips(hostname, resolved)
      return (False, err_msg) if not ok else (True, None)
  except socket.gaierror as dns_err:
      return False, f"Fallo en resolución DNS para '{hostname}': {dns_err}"
  ```
- **Solución Técnica Propuesta:**
  1. Eliminar la clase duplicada `SSRFValidationError` de `jg_agente/app/security/ip_policy.py:13` e importar `from jg_sdk.security.ssrf import SSRFValidationError`.
  2. En `validate_url`, `validate_url_async`, `resolve_and_pin_url` y `resolve_and_pin_url_async` (`jg_agente/app/security/ssrf_validator.py`), capturar `except (socket.gaierror, SSRFValidationError) as dns_err:`.
- **Criterios de Aceptación (Checklist verificable):**
  - [x] Test en `jg_agente/tests/test_ssrf_validator.py` que mockea `socket.getaddrinfo` (en vez de `validator.resolve_host`) lanzando `socket.gaierror` y verifica que `validate_url()` retorna `(False, ...)` sin propagar excepción no controlada.
