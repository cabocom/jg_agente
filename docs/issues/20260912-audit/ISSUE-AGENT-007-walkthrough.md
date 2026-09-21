# Walkthrough: [ISSUE-AGENT-007] Persistencia atómica y permisos POSIX en CredentialStore

## 1. Resumen de Cambios

### Core de Registro (`app/core/registration.py`)
- **[CredentialStore.save](../../../app/core/registration.py)**:
  - Creación de archivo temporal `target.with_name(f"{target.name}.tmp")` en el mismo directorio.
  - Creación y apertura mediante `os.open(tmp_target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`.
  - Aplicación explícita de `os.fchmod(fd, 0o600)` en sistemas POSIX.
  - Escritura de datos, vaciado de buffers con `f.flush()` y sincronización forzada a hardware de almacenamiento con `os.fsync(f.fileno())`.
  - Reemplazo atómico con `os.replace(tmp_target, target)`.
  - Limpieza de archivo temporal `.tmp` ante cualquier fallo o excepción no controlada mediante `contextlib.suppress(OSError)`.

### Pruebas Automatizadas (`tests/test_registration_client.py`)
- **`test_credential_store_save_atomic_fsync_and_replace`**:
  - Verifica que `os.fsync` y `os.replace` se invocan en el orden correcto y que el archivo temporal `.tmp` desaparece al culminar.
- **`test_credential_store_save_atomic_failure_cleanup`**:
  - Verifica que si ocurre un fallo de E/S (`OSError`) durante `fsync`, el archivo `.tmp` se limpia y el archivo de credenciales previo permanece íntegro y sin modificaciones.

## 2. Verificación Automatizada

### Pruebas Específicas
```bash
.venv/bin/pytest tests/test_registration_client.py -v
```
Resultado: 22 passed (100%).

### Verificación Integral (`scripts/check.sh`)
- **Ruff:** 100 archivos conforme a formato y linter sin advertencias.
- **MyPy:** Chequeo de tipos estricto superado sin errores en 100 archivos fuente.
- **Pytest:** 340/340 tests pasando al 100%.
