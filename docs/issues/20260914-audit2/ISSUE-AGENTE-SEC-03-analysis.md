# Análisis Técnico: [AGENTE-SEC-03] Evasión de Filtro de Directory Traversal por Falta de Normalización

## Metadatos
- **Issue ID:** [jg_agente#59](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/59)
- **Severidad:** 🟠 ALTO
- **CWE:** CWE-22 (Improper Limitation of a Pathname to a Restricted Directory)
- **Componentes Afectados:**
  - `jg_agente/app/security/guard.py` (`SecurityGuard.evaluate`, `_check_directory_traversal_or_protected_path`, `PROTECTED_SYSTEM_PATHS`)
  - `jg_agente/tests/test_security_guard.py`
- **Fecha:** Septiembre 2026

---

## 1. Descripción del Problema y Causa Raíz

En la implementación anterior de `SecurityGuard.evaluate` (`jg_agente/app/security/guard.py`), la detección de Directory Traversal se basaba en comprobaciones ingenuas de prefijos y subcadenas:

```python
# Código vulnerable anterior:
if ".." in arg_val or arg_val.startswith("/proc") or arg_val.startswith("/etc"):
    for sys_path in PROTECTED_SYSTEM_PATHS:
        if arg_val == sys_path or arg_val.startswith(sys_path + "/"):
            # Denegar acceso
```

### Vulnerabilidades y Vectores de Evasión:
1. **Evasión de Prefijo por Directory Traversal (`..`):**
   Aunque `".." in arg_val` evaluaba a `True`, el bucle interno exigía que la cadena literal empezara por la ruta protegida (`arg_val.startswith(sys_path + "/")`).
   Un payload como `"/tmp/../../../../etc/shadow"` comienza literalmente por `"/tmp"`, por lo que la condición `arg_val.startswith("/etc/")` devolvía `False` y la comprobación era burlada completamente.
2. **Falta de Resolución de Enlaces Simbólicos (Symlinks):**
   No se utilizaba `os.path.realpath()`. Si existía o se creaba un enlace simbólico en un directorio permitido (e.g. `/tmp/innocent.txt -> /etc/passwd`), el valor textual pasaba la validación sin alertar que el destino real era un archivo sensible del sistema operativo.
3. **Falta de Normalización de Rutas Relativas y Codificación URL:**
   Payloads como `"../../../../etc/shadow"`, `"///etc///shadow"`, `"/./etc/./passwd"` o codificados en URL (`"/tmp/%2e%2e/%2e%2e/etc/shadow"`) evadían los filtros basados en igualdad o prefijos fijos.
4. **Disparidades entre Plataformas (Linux vs Darwin/macOS):**
   En entornos basados en Darwin o distribuciones con usr-merge/symlinks (`/etc -> /private/etc`, `/var/run -> /run`, `/root -> /var/root`), las rutas canónicas del sistema pueden tener prefijos reales distintos a los definidos en listas estáticas.

---

## 2. Impacto Técnico y de Seguridad

- **Confidencialidad e Integridad:** Severidad ALTA (CWE-22).
- Permite a un atacante leer archivos críticos del sistema (`/etc/shadow`, `/etc/passwd`, `/proc/self/environ`, llaves SSH en `~root/.ssh/id_rsa`, o interactuar con el socket del daemon en `/run/docker.sock`), eludiendo el sandbox lógico del agente.

---

## 3. Solución Arquitectónica Implementada

### A. Catálogo Expandido de Rutas Protegidas Canónicas (`_build_protected_paths`)
Se amplió el catálogo de rutas base para contemplar `/run`, `/var/root`, `/private/etc`, etc., resolviendo además dinámicamente mediante `os.path.realpath()` en tiempo de inicialización todas las equivalencias canónicas del sistema operativo anfitrión.

### B. Normalización Canónica Integral (`_check_directory_traversal_or_protected_path`)
Se implementó un evaluador exhaustivo que:
1. Ignora URLs web (`http://`, `https://`) para no interferir con las validaciones de red (delegadas a `SSRFValidator`).
2. Descodifica secuencias URL (`urllib.parse.unquote`) y normaliza separadores Windows (`\\` a `/`).
3. Normaliza puntos relativos mediante `os.path.normpath`.
4. Resuelve enlaces simbólicos y rutas canónicas mediante `os.path.realpath`.
5. Si contiene `..` relativo, evalúa la proyección canónica normalizada desde la raíz (`/`) y desde el directorio de trabajo (`os.path.abspath`).
6. Si contiene prefijos de usuario (`~`), expande mediante `os.path.expanduser`.
7. Si cualquiera de las rutas candidatas resueltas coincide o reside bajo un directorio de `PROTECTED_SYSTEM_PATHS`, emite bloqueo determinista `PolicyDecision.DENY`.

---

## 4. Verificación y Cobertura de Pruebas

Se añadieron nuevos casos de prueba en `jg_agente/tests/test_security_guard.py`:
- `test_blocks_directory_traversal_with_normalization`: Valida el bloqueo de `/tmp/../../../../etc/shadow`, `../../../../etc/shadow`, `foo/../../../../etc/passwd`, `/var/run/../../etc/shadow`, `///etc///shadow`, `/./etc/./passwd`, `/tmp/%2e%2e/%2e%2e/etc/shadow`, `~root/.ssh/id_rsa`, `/run/docker.sock`, etc.
- `test_blocks_symlink_pointing_to_protected_path`: Valida mediante enlaces simbólicos reales en `tmp_path` que apuntan a `/etc/passwd` que la resolución `realpath` bloquea el acceso.
- `test_allows_safe_files_and_relative_paths`: Verifica la ausencia de falsos positivos en archivos de aplicación legítimos (`safe_file.txt`, `data/results.csv`, `/tmp/app_export.txt`, `/home/appuser/report.md`).
