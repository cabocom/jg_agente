### ✅ Resolución y Cierre de Issue [AGENTE-SEC-02]

**Issue:** [jg_agente#58](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/58)
**Título:** [AGENTE-SEC-02] Evasión de Filtro de Inyección Shell por Restricción de Nombre de Argumentos
**Severidad:** 🟠 ALTO
**CWE:** CWE-78 (Improper Neutralization of Special Elements used in an OS Command)

---

#### 1. Causa Raíz Identificada
El interceptor `SecurityGuard.evaluate` restringía la verificación de inyección de comandos shell únicamente a aquellos argumentos cuyas claves contuvieran las subcadenas `"command"`, `"name"`, `"service"` o `"host"`. Argumentos con nombres como `"target"`, `"input"`, `"script"`, `"query"`, `"cmd"`, `"args"`, `"path"` o anidados dentro de listas/diccionarios evadían completamente la validación.

#### 2. Cambios Implementados
- **Extracción Recursiva (`_extract_string_arguments`):** Se introdujo una función para extraer todos los argumentos de tipo string independientemente de la profundidad de la estructura de datos.
- **Validación Universal Incondicional:** Se eliminó el filtro de coincidencia por nombre de clave; ahora todos los argumentos tipo string son evaluados ante el patrón de inyección shell (`SHELL_INJECTION_PATTERN`).
- **Soporte Seguro para URLs (`URL_SHELL_INJECTION_PATTERN`):** Se implementó una regla adaptada para cadenas que comiencen por `http://` o `https://`, permitiendo delimitadores normales de query string (`&`) pero bloqueando estrictamente delimitadores shell (`;`, `` ` ``, `$`, `|`, `>`, `<`, `\n`, `\r`, `\\`).
- **Cobertura de Pruebas:** Se añadieron pruebas unitarias en `jg_agente/tests/test_security_guard.py` verificando el bloqueo en argumentos arbitrarios, estructuras anidadas y compatibilidad de URLs.

#### 3. Verificación y Resultados
- **Ruff & MyPy:** Comprobación estricta de tipos y formato 100% limpia sin advertencias.
- **Pytest:** 371 tests pasando satisfactoriamente.
- **Documentación de Auditoría:** Generados los análisis técnicos y walkthroughs en `jg_agente/docs/audit2/ISSUE-AGENTE-SEC-02-*`.
