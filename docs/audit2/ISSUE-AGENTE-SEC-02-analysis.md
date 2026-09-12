# Análisis Técnico: [AGENTE-SEC-02] Evasión de Filtro de Inyección Shell por Restricción de Nombre de Argumentos

## Metadatos
- **Issue ID:** [jg_agente#58](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/58)
- **Severidad:** 🟠 ALTO
- **CWE:** CWE-78 (Improper Neutralization of Special Elements used in an OS Command)
- **Componentes Afectados:**
  - `jg_agente/app/security/guard.py` (`SecurityGuard.evaluate`, `_extract_string_arguments`, `SHELL_INJECTION_PATTERN`, `URL_SHELL_INJECTION_PATTERN`)
  - `jg_agente/tests/test_security_guard.py`
- **Fecha:** Septiembre 2026

---

## 1. Descripción del Problema y Causa Raíz

En la implementación previa de `SecurityGuard.evaluate` (`jg_agente/app/security/guard.py`), la verificación de inyección de comandos shell estaba condicionada por una lista fija y restrictiva de nombres de clave:

```python
# Código vulnerable anterior:
if (
    "command" in arg_key
    or "name" in arg_key
    or "service" in arg_key
    or "host" in arg_key
) and SHELL_INJECTION_PATTERN.search(arg_val):
    reason = (
        f"Violación de seguridad: Caracteres sospechosos de inyección "
        f"shell detectados en argumento '{arg_key}': '{arg_val}'"
    )
    ...
    return eval_res
```

### Deficiencias Identificadas:
1. **Bypass por Nombres de Argumentos No Contemplados:**
   Cualquier plugin actual o futuro cuyas herramientas definieran argumentos con nombres típicos de ejecución o entrada tales como:
   - `target` (e.g. `ping_target`, `scan_target`)
   - `input` / `data` (e.g. `script_input`)
   - `script` / `cmd` / `args` / `query`
   - `path` / `file` / `container`
   esquivaban totalmente el patrón regex `SHELL_INJECTION_PATTERN`, permitiendo pasar cargas útiles maliciosas como `target="localhost && cat /etc/passwd"` o `script="test.sh; id"`.
2. **Ausencia de Inspección Recursiva en Estructuras Anidadas:**
   La comprobación solo iteraba sobre el primer nivel del diccionario `tool_args`. Si un parámetro contenía listas (e.g. `options: ["--flag", "val; rm -rf /"]`) o diccionarios anidados (e.g. `config: {"target": "foo | bar"}`), la comprobación no alcanzaba dichos valores.

---

## 2. Impacto Técnico y de Seguridad

- **Confidencialidad, Integridad y Disponibilidad:** Severidad ALTA (CWE-78).
- Si una herramienta de sistema o plugin recibía argumentos externos sin sanitización en capas inferiores y confiaba en la puerta de enlace de `SecurityGuard`, un atacante a través de inyección de prompts o manipulación de parámetros de API podía forzar la ejecución de comandos arbitrarios del sistema operativo anfitrión o del contenedor.

---

## 3. Solución Arquitectónica Implementada

### A. Inspección Recursiva Universal (`_extract_string_arguments`)
Se introdujo una función utilitaria recursiva en `jg_agente/app/security/guard.py`:
```python
def _extract_string_arguments(args: Any, parent_key: str = "") -> list[tuple[str, str]]:
    """Extrae recursivamente todas las tuplas (clave_completa, valor_str) de los argumentos."""
    result: list[tuple[str, str]] = []
    if isinstance(args, dict):
        for k, v in args.items():
            full_key = f"{parent_key}.{k}" if parent_key else str(k)
            result.extend(_extract_string_arguments(v, full_key))
    elif isinstance(args, list | tuple | set):
        for idx, item in enumerate(args):
            full_key = f"{parent_key}[{idx}]"
            result.extend(_extract_string_arguments(item, full_key))
    elif isinstance(args, str):
        result.append((parent_key, args))
    return result
```

### B. Eliminación de la Restricción de Nombre de Argumentos
En `SecurityGuard.evaluate`:
- Se eliminó el filtro condicional `if ("command" in arg_key or "name" in arg_key or ...)`.
- Ahora todos los valores de tipo `str` extraídos son evaluados frente al patrón de inyección shell de forma incondicional.

### C. Soporte Seguro de URLs (`URL_SHELL_INJECTION_PATTERN`)
Para no romper parámetros legítimos de cadenas de consulta en URLs HTTP/HTTPS (donde el carácter `&` y comillas son sintaxis válida de query strings):
- Se distingue si `arg_val.startswith(("http://", "https://"))`.
- En caso de URL, se aplica `URL_SHELL_INJECTION_PATTERN = re.compile(r"[;`$\n\r><|\\]")`, garantizando que delimitadores peligrosos de shell (`;`, backticks, `$()`, pipes, redirecciones, nuevas líneas) sigan siendo bloqueados de raíz, al tiempo que se permite `https://api.cabocom.net/weather?city=Madrid&lang=es`.
- Para el resto de argumentos generales, se aplica el patrón estricto `SHELL_INJECTION_PATTERN = re.compile(r"[;&$`\n\r><|\\'\"]")`.

---

## 4. Verificación y Cobertura de Pruebas

Se incorporaron casos de prueba exhaustivos en `jg_agente/tests/test_security_guard.py`:
1. `test_blocks_shell_injection_on_unrestricted_argument_names`:
   Verifica que nombres como `target`, `input`, `script`, `query`, `cmd`, `args`, `path`, `container` sean bloqueados con decisión `PolicyDecision.DENY` al contener metacaracteres shell.
2. `test_blocks_nested_shell_injection`:
   Verifica la detección y bloqueo en listas y diccionarios anidados.
3. `test_allows_safe_url_query_strings_but_blocks_url_shell_injection`:
   Verifica la compatibilidad con URLs legítimas con `&` y el bloqueo de URLs manipuladas con delimitadores de inyección shell.
