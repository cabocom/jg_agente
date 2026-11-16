# Issue 06: [jg_agente] Refactor: Adopción del módulo unificado jg_sdk.security.ssrf y desprecado de internals privados

- **Título:** `[jg_agente] Refactor: Adopción del módulo unificado jg_sdk.security.ssrf y desprecado de internals privados`
- **Prioridad y Fase:** Media | Fase 2: Runtime Determinista
- **Dependencias:** Issue 02 (`[jg_agente_sdk] Refactor: Centralización del módulo unificado de protección SSRF y DNS Pinning`)
- **Contexto Técnico y Archivos Afectados:**
  - Hallazgos del informe: `H-07` (`SSRFSafeAsyncBackend` depende de clases internas privadas de `httpcore`) y `H-08` (Código duplicado entre el core de `jg_agente` y múltiples plugins).
  - Archivos a modificar:
    - `jg_agente/app/security/ssrf_validator.py`
    - `jg_agente/app/security/dns_pinning.py`
    - `jg_agente/app/security/safe_http_client.py`
    - `jg_agente/tests/test_ssrf_protection.py`

---

## Especificación Técnica

### 1. `jg_agente/app/security/dns_pinning.py` y `ssrf_validator.py`
- Reemplazar la lógica duplicada de resolución y validación de IPs delegando en `jg_sdk.security.ssrf`.
- Mantener las clases en `app.security.*` como fachadas ligeras (*thin wrappers*) para preservar la compatibilidad hacia atrás con el código existente del core y no romper imports preexistentes.
- Eliminar la importación directa de `httpcore._backends.anyio` y `httpcore._backends.sync` en favor del transporte estandarizado y seguro exportado por `jg_sdk`.

---

## Criterios de Aceptación (Checklist Verificable)

- [ ] Todas las pruebas existentes de seguridad en `jg_agente/tests/test_ssrf_*.py` continúan pasando al 100% sin regresiones.
- [ ] No existen referencias a módulos privados con guión bajo (`_backends`) en `jg_agente/app/security/`.
- [ ] Pruebas unitarias de DNS Pinning validando que el comportamiento de fijado de IP ante resoluciones multi-IP se mantiene intacto.
- [ ] Linters: `ruff check app/security` sin errores ni excepciones ignoradas.
