### ✅ Resolución y Cierre de Issue [AGENTE-SEC-03]

**Issue:** [jg_agente#59](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/59)
**Título:** [AGENTE-SEC-03] Evasión de Filtro de Directory Traversal por Falta de Normalización
**Severidad:** 🟠 ALTO
**CWE:** CWE-22 (Improper Limitation of a Pathname to a Restricted Directory)

---

#### 1. Causa Raíz Identificada
La validación previa utilizaba comprobaciones de subcadenas e inicios de cadena (`arg_val.startswith("/etc/")`), sin resolver enlaces simbólicos ni secuencias de escape `..`. Payloads como `"/tmp/../../../../etc/shadow"` comenzaban literalmente por `"/tmp"` y eludían la condición `startswith`, permitiendo acceder a archivos protegidos. Asimismo, enlaces simbólicos a archivos restringidos no eran detectados.

#### 2. Cambios Implementados
- **Resolución Canónica Exhaustiva:** Se implementó `_check_directory_traversal_or_protected_path()` en `jg_agente/app/security/guard.py`, utilizando `os.path.normpath()`, `os.path.abspath()` y `os.path.realpath()` para resolver canónicamente cualquier ruta antes de compararla contra `PROTECTED_SYSTEM_PATHS`.
- **Detección de Symlinks y Traversal Relativo:** Se garantiza la resolución de enlaces simbólicos en tiempo de ejecución y la normalización de secuencias `..` tanto relativas al directorio de trabajo como proyectadas a la raíz.
- **Descodificación URL y Expansión de Usuario:** Neutralización de bypasses codificados (`urllib.parse.unquote`) y referencias `~` (`os.path.expanduser`).
- **Cobertura de Pruebas:** Se incorporaron casos de prueba unitarios en `jg_agente/tests/test_security_guard.py` cubriendo payloads de evasión de traversal, symlinks a `/etc/passwd` y validación de no-regresión en rutas seguras de aplicación.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Formato y tipado estricto aprobados sin advertencias.
- **Pytest:** 374 tests ejecutados y pasando al 100%.
- **check.sh Global:** Verificación global del sistema (Agente, Dashboard y Selenium E2E) completada con éxito.
