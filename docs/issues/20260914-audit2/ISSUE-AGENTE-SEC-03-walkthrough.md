# Walkthrough Técnico: [AGENTE-SEC-03] Evasión de Filtro de Directory Traversal por Falta de Normalización

## Resumen del Cambio
Se ha sustituido la validación textual de rutas por una verificación canónica basada en `os.path.normpath`, `os.path.abspath` y `os.path.realpath`. Esto neutraliza cualquier intento de Directory Traversal (CWE-22) basado en secuencias `..`, prefijos engañosos, barras redundantes, enlaces simbólicos (symlinks) o codificación URL.

---

## Modificaciones Realizadas

### 1. Hardening en `jg_agente/app/security/guard.py`
- Se importaron `os` y `urllib.parse`.
- Se amplió `_BASE_PROTECTED_SYSTEM_PATHS` con rutas modernas y equivalencias de sistema (`/run`, `/var/root`, `/private/etc`, etc.).
- Se implementó `_build_protected_paths()` para resolver enlaces canónicos del host en tiempo de inicio.
- Se implementó `_check_directory_traversal_or_protected_path(arg_val: str) -> tuple[bool, str]`:
  - Descodifica codificación URL (`urllib.parse.unquote`).
  - Normaliza puntos y barras (`os.path.normpath`).
  - Resuelve enlaces simbólicos del sistema (`os.path.realpath`).
  - Resuelve secuencias relativas escapadas (`normpath(join("/", ...))` y `abspath`).
  - Expande referencias de usuario (`os.path.expanduser`).
- En `SecurityGuard.evaluate`: Se invoca la función de normalización sobre cada argumento tipo string extraído de `tool_args`.

### 2. Pruebas Unitarias de Seguridad
- **Archivo:** `jg_agente/tests/test_security_guard.py`
- Añadidos:
  - `test_blocks_directory_traversal_with_normalization`: Cobertura completa de payloads de evasión de traversal.
  - `test_blocks_symlink_pointing_to_protected_path`: Cobertura de symlinks maliciosos.
  - `test_allows_safe_files_and_relative_paths`: Verificación de no-regresión y ausencia de falsos positivos en rutas válidas.

---

## Resultados de Verificación
- **Ruff:** Linter y formato 100% limpios (`106 files already formatted`).
- **MyPy:** Comprobación estricta de tipos correcta (`Success: no issues found in 106 source files`).
- **Pytest:** 374 pruebas ejecutadas y aprobadas (100% pasando).
