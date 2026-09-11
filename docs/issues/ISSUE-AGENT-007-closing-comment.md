### Resolución de [ISSUE-AGENT-007] Persistencia atómica y permisos POSIX en CredentialStore (GitLab #48)

Se ha completado la resolución del issue AGENT-007 blindando la persistencia y los permisos de las credenciales del agente en `CredentialStore.save()`:

1. **Escritura en Archivo Temporal `.tmp` y Permisos 0600 Inmediatos:**
   - La escritura se realiza en un archivo temporal en el mismo directorio (`target.with_name(f"{target.name}.tmp")`).
   - El descriptor se crea directamente con permisos `0o600` (`os.open` y `os.fchmod` en POSIX), eliminando cualquier ventana temporal de exposición bajo la umask del sistema.

2. **Sincronización Física a Disco (`os.fsync`) y Sustitución Atómica (`os.replace`):**
   - Se asegura la durabilidad física forzando el volcado a disco con `os.fsync(f.fileno())` antes de cerrar el descriptor.
   - La sustitución del archivo final se realiza atómicamente con `os.replace(tmp_target, target)`.
   - Ante cualquier excepción o interrupción en el proceso, el archivo temporal se destruye de forma defensiva y el archivo previo permanece intacto.

3. **Verificación y Pruebas:**
   - Se agregaron tests unitarios dedicados en `tests/test_registration_client.py` verificando el orden de invocación de `fsync`/`replace` y la limpieza defensiva ante errores.
   - La suite completa de `jg_agente` supera todas las comprobaciones (`scripts/check.sh` conforme en Ruff, MyPy estricto y Pytest con 340/340 tests pasando al 100%).

/close
