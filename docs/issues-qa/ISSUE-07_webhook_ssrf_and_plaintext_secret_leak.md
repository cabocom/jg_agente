# [ISSUE-07] [jg_agente] fix(security): Proteger webhooks de notificación contra SSRF y eliminar envío de PERMANENT_AGENT_SECRET en texto plano

- **ID Maestro QA:** `ISSUE-07`
- **Proyecto Destino:** `javiergalvez-ia/jg_agente`
- **Asignado a:** `cabocom` / Javier Gálvez (`assignee_ids: [553306]`)
- **Milestone:** `QA & Anti-Fallback Hardening (Nov-Dic 2026)`
- **Labels:** `qa-audit, priority::blocker, security`
- **GitLab Issue Remoto:** [jg_agente#88](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/88)

---

- **Severidad y Categoría:** `Blocker` | `Seguridad`
- **Consenso de Auditores:** Detectado por: `argon` | Omitido por: `claude-sonnet`, `flash-3.8`, `hydrogen`
- **Evidencia Exacta:**
  - `jg_agente/app/services/execution_notification_service.py:40-53, 80-119`
  - `jg_agente/app/services/background_execution_service.py:19-30`
  - `jg_agente/app/core/registration_client.py:93-96`
  ```python
  # jg_agente/app/services/execution_notification_service.py:51-53, 105-108
  if secret:
      headers["Authorization"] = f"Bearer {secret}"
      headers["X-Agent-Secret"] = secret
  ...
  async with httpx.AsyncClient(timeout=timeout) as client:
      resp = await client.post(target_url, json=payload, headers=headers)
  ```
- **Solución Técnica Propuesta:**
  1. En `execution_notification_service.py`, validar `target_url` con `SSRFValidator` (o usar `create_async_ssrf_safe_client`) antes de enviar cualquier petición webhook.
  2. Eliminar el envío en texto plano de `PERMANENT_AGENT_SECRET` en las cabeceras `Authorization` y `X-Agent-Secret` tanto en `execution_notification_service.py:51-53` como en `registration_client.py:93-96`; utilizar exclusivamente cabeceras firmadas con HMAC-SHA256 (`X-Agent-ID`, `X-Timestamp`, `X-Nonce`, `X-Signature`).
- **Criterios de Aceptación (Checklist verificable):**
  - [x] `notify_execution_completion` rechaza `callback_url` que apunten a IPs bloqueadas/metadata cloud (`169.254.169.254`, `127.0.0.1` no autorizados).
  - [x] Ninguna petición saliente de `execution_notification_service.py` ni `registration_client.py` contiene `PERMANENT_AGENT_SECRET` en claro en las cabeceras HTTP.
  - [x] Nuevos tests de seguridad en `tests/test_execution_async_notifications.py` y `tests/test_registration_client.py`.
