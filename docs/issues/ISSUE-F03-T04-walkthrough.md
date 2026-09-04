# Walkthrough: ISSUE-F03-T04 — Implementación de validador de protección SSRF para tools de red

> **Issue ID:** ISSUE-F03-T04  
> **Fase:** FASE 03 (Persistencia y Checkpointing)  
> **Resultado:** Éxito (79 tests pasando, MyPy strict 0 errores, Ruff limpio)  

---

## 1. Resumen de Cambios

En este issue se implementó el módulo de protección contra Server-Side Request Forgery (`SSRFValidator`), protegiendo la invocación de herramientas de red contra accesos no autorizados a servicios internos, metadatos de nube y redes privadas.

### Archivos Afectados

- **`app/core/config.py`**:
  - Incorporadas variables de entorno de seguridad SSRF: `SSRF_ENFORCE_PROTECTION`, `SSRF_ALLOWED_HOSTS`, `SSRF_ALLOWED_NETWORKS`, `SSRF_ALLOW_PRIVATE_NETWORKS`.
- **`app/security/ssrf.py`**:
  - Implementación de `SSRFValidator`, excepción `SSRFValidationError` y factoría singleton `get_ssrf_validator()`.
  - Definición de rangos bloqueados `DEFAULT_BLOCKED_NETWORKS` (RFC 1918, RFC 4193, loopback, metadata de nube 169.254.169.254, etc.).
  - Comprobación de esquemas (`http`, `https`), hostnames prohibidos y resolución DNS anti-rebinding.
  - Método `validate_tool_arguments_for_ssrf` para escaneo de argumentos procedentes del LLM.
- **`app/security/__init__.py`**:
  - Exportación de `SSRFValidator`, `SSRFValidationError` y `get_ssrf_validator`.
- **`tests/test_ssrf_validator.py`**:
  - Suite exhaustiva de pruebas unitarias verificando bloqueo de loopback, metadatos IMDS, redes privadas, allowlists de hosts/subredes, URLs de texto y argumentos de tools.
- **`docs/security.md`** y **`README.md`**:
  - Documentación de la arquitectura de defensa SSRF y actualización del estado del proyecto.

---

## 2. Evidencia de Ejecución

### Ejecución de Linter, Tipado y Suite de Tests (`./scripts/check.sh`)

```bash
$ ./scripts/check.sh
========================================
🔍 Ejecutando verificación de código...
========================================

1️⃣  [Ruff] Análisis de formato y linter...
All checks passed!
26 files already formatted

2️⃣  [MyPy] Chequeo estático de tipos estricto...
Success: no issues found in 26 source files

3️⃣  [Pytest] Ejecución de suite de tests...
........................................................................ [ 91%]
.......                                                                  [100%]
79 passed in 0.85s

========================================
✅ ¡Todas las comprobaciones pasaron con éxito!
========================================
```

---

## 3. Próximos Pasos

Continuar con la culminación de la Fase 03 o avanzar hacia la Fase 04 (Motor de Seguridad `SecurityGuard`).
