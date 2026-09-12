# Análisis Técnico: [ISSUE-AGENT-007] Persistencia atómica y permisos POSIX en CredentialStore

## 1. Diagnóstico del Estado Previo
En `app/core/registration.py:60-83`:
```python
@classmethod
def save(cls, credentials: AgentCredentials, path: Path | str | None = None) -> None:
    target = cls.resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    data = credentials.model_dump(mode="json")
    json_content = json.dumps(data, indent=2, ensure_ascii=False)

    target.write_text(json_content, encoding="utf-8")

    if os.name == "posix":
        try:
            os.chmod(target, 0o600)
        except OSError as e:
            ...
```
Problemas técnicos detectados:
1. `Path.write_text()` abre el archivo con `open(target, 'w')`, truncando a 0 bytes el archivo de forma no atómica.
2. Si el sistema colapsa durante la escritura, el archivo queda truncado.
3. El archivo se crea con la umask del entorno antes de ejecutar `chmod`, dejando los bytes legibles durante esa ventana de tiempo.
4. No se utiliza `fsync`, dejando el volcado a discreción de los buffers de la capa de E/S del sistema operativo.

## 2. Solución Diseñada

### 2.1 Uso de Archivo Temporal `.tmp` en el Mismo Inodo/Filesystem
- Se utiliza `tmp_target = target.with_name(f"{target.name}.tmp")`.
- Al residir en el mismo directorio, se garantiza que tanto el origen temporal como el destino final pertenezcan al mismo sistema de archivos montado, permitiendo que la llamada `os.replace` sea una operación atómica a nivel de tabla de inodos del sistema de archivos.

### 2.2 Apertura con Permisos 0600 desde el Descriptor
- Se utiliza `os.open(tmp_target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`.
- Se refuerza en POSIX con `os.fchmod(fd, 0o600)`.
- El archivo nace protegido desde el primer instante; ningún otro usuario puede leerlo.

### 2.3 Sincronización Forzada a Disco (`os.fsync`)
- Se escribe el contenido codificado en UTF-8.
- Se ejecuta `f.flush()` y `os.fsync(f.fileno())`.
- Esto garantiza la durabilidad real (propiedad ACID "D") ante pérdidas repentinas de energía o caídas del kernel.

### 2.4 Reemplazo Atómico con `os.replace`
- Se cierra el descriptor de archivo (evitando bloqueos en sistemas que requieren cierre de handles antes de mover archivos).
- Se ejecuta `os.replace(tmp_target, target)`.
- Si `target` ya existía, la sustitución es instantánea e indivisible: ningún lector del archivo podrá encontrar un estado a medio escribir.

### 2.5 Limpieza Defensiva
- En caso de excepción en cualquier punto de la secuencia, se captura la excepción, se elimina `tmp_target` defensivamente con `contextlib.suppress(OSError)` y se relanza la excepción.

## 3. Pruebas Automatizadas
Se añadieron dos tests en `tests/test_registration_client.py`:
1. `test_credential_store_save_atomic_fsync_and_replace`: Espía las llamadas a `os.fsync` y `os.replace`, validando que `fsync` se ejecuta antes de `replace` y que `.tmp` no queda residual en disco.
2. `test_credential_store_save_atomic_failure_cleanup`: Simula un fallo de disco (`OSError`) durante `os.fsync` y verifica que el archivo temporal `.tmp` es destruido y que el archivo original previo no sufre corrupción alguna.
