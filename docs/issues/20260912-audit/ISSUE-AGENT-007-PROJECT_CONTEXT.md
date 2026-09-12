# Contexto de Proyecto: [ISSUE-AGENT-007] Persistencia atómica y permisos POSIX en CredentialStore

## 1. Identificación y Estado
- **Issue ID:** ISSUE-AGENT-007
- **GitLab Item:** #48 (jg_agente)
- **Vínculo Auditoría:** AGENT-007
- **Fase:** Fase Post-Auditoría (Implementación de Hallazgos Codex)
- **Prioridad:** Low / Security & Operations
- **Complejidad Estimada:** S
- **Estado:** Implementado / Verificado

## 2. Alineación Arquitectónica
En la auditoría técnica independiente (hallazgo AGENT-007), se constató que la clase `CredentialStore` (`app/core/registration.py`), responsable de persistir localmente las credenciales y el secreto permanente del agente (`.agent_credentials.json`), utilizaba una escritura directa mediante `target.write_text(json_content)` seguida de una llamada diferida a `os.chmod(target, 0o600)`.

Este mecanismo presentaba dos vulnerabilidades críticas en producción:
1. **Corrupción por interrupción (Falta de atomicidad):** Si el contenedor o proceso era reiniciado abruptamente (corte de energía, OOM killer, terminación SIGKILL) durante `write_text`, el archivo de credenciales quedaba truncado o a medio escribir. Esto dejaba al agente inoperativo y forzaba a un re-aprovisionamiento manual en el Dashboard con un nuevo bootstrap token.
2. **Ventana de exposición de permisos (Race Condition):** Al crearse el archivo inicialmente con `write_text`, se aplicaba la máscara por defecto del sistema (`umask`), dejando una ventana temporal donde otros usuarios o procesos en el host podían leer el secreto permanente antes de que se ejecutara `os.chmod`.
3. **Persistencia volátil en buffers de sistema operativo:** Sin una sincronización forzada a hardware (`fsync`), los datos podían permanecer en la caché de páginas del kernel de Linux sin estar efectivamente escritos en el disco.

Para resolver estas vulnerabilidades de forma robusta y conforme al estándar POSIX:
1. **Escritura en Archivo Temporal `.tmp` en el Mismo Filesystem:**
   - Se crea el archivo temporal `target.with_name(f"{target.name}.tmp")` en el mismo directorio que el archivo final, condición indispensable para que `os.replace` opere como una renombración atómica a nivel de inodo en el sistema de archivos.
2. **Permisos Restrictivos 0600 desde la Creación:**
   - Se abre el descriptor con `os.open(tmp_target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)`.
   - En sistemas POSIX, se ejecuta de inmediato `os.fchmod(fd, 0o600)` sobre el descriptor antes de escribir cualquier dato, garantizando que el archivo nunca exista en disco con permisos permisivos.
3. **Sincronización a Disco con `os.fsync`:**
   - Se escribe el JSON y se llama a `f.flush()` y `os.fsync(f.fileno())` forzando el vaciado físico a los platos/bloques de almacenamiento.
4. **Reemplazo Atómico con `os.replace`:**
   - Una vez cerrado el descriptor de forma segura, se ejecuta `os.replace(tmp_target, target)`. La sustitución es indivisible: los procesos lectores ven la versión antigua o la versión nueva completa, nunca un archivo vacío o a medio escribir.
5. **Limpieza Defensiva ante Excepciones:**
   - Si ocurre un fallo de I/O, disco lleno o interrupción, el archivo temporal `.tmp` se elimina inmediatamente y el archivo de credenciales previo permanece inalterado.

## 3. Criterios de Aceptación
- `CredentialStore.save()` crea primero un archivo `.tmp` con permisos `0600` en POSIX.
- Se invoca `os.fsync` para asegurar persistencia durable antes del reemplazo.
- Se utiliza `os.replace` para garantizar atomicidad sin estados intermedios inconsistentes.
- Ante fallos simulados durante la escritura o sincronización, el `.tmp` se limpia y el archivo destino previo permanece intacto.
- La suite completa de pruebas en `jg_agente` pasa al 100% (340 tests).
