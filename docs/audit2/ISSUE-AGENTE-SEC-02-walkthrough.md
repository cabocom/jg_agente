# Walkthrough Técnico: [AGENTE-SEC-02] Evasión de Filtro de Inyección Shell por Restricción de Nombre de Argumentos

## Resumen del Cambio
Se ha eliminado la restricción de nombres de clave (`"command"`, `"name"`, `"service"`, `"host"`) en la validación de inyección shell del `SecurityGuard`. A partir de ahora, el interceptor inspecciona recursivamente todos los argumentos de tipo string en cualquier estructura de datos (incluyendo diccionarios y listas anidados) garantizando que ninguna herramienta o plugin pueda sufrir evasión de filtros de inyección de comandos del sistema operativo (CWE-78).

---

## Modificaciones Realizadas

### 1. Extracción Recursiva y Validación Universal
- **Archivo modificado:** `jg_agente/app/security/guard.py`
- **Función auxiliar agregada:** `_extract_string_arguments(args: Any, parent_key: str = "") -> list[tuple[str, str]]`
  Permite recorrer colecciones jerárquicas arbitrarias y retornar todas las rutas de argumento con sus respectivos valores `str`.
- **Patrón regex especializado para URLs:**
  `URL_SHELL_INJECTION_PATTERN = re.compile(r"[;`$\n\r><|\\]")`
  Evita falsos positivos en URLs legítimas con parámetros de consulta (`&` y comillas), mientras previene la inyección de comandos mediante delimitadores y caracteres de control shell.
- **Lógica de evaluación en `SecurityGuard.evaluate`:**
  Sustituido el bucle superficial por:
  ```python
  # 2. Comprobación Universal de Inyección de Comandos Shell y Directory Traversal
  for arg_key, arg_val in _extract_string_arguments(tool_args):
      # Directory Traversal
      if ".." in arg_val or arg_val.startswith("/proc") or arg_val.startswith("/etc"):
          for sys_path in PROTECTED_SYSTEM_PATHS:
              if arg_val == sys_path or arg_val.startswith(sys_path + "/"):
                  ...
                  return eval_res

      # Comprobación Universal Shell Injection
      is_url = arg_val.startswith(("http://", "https://"))
      pattern_to_use = URL_SHELL_INJECTION_PATTERN if is_url else SHELL_INJECTION_PATTERN
      if pattern_to_use.search(arg_val):
          ...
          return eval_res
  ```

### 2. Pruebas Unitarias de Regresión y Seguridad
- **Archivo modificado:** `jg_agente/tests/test_security_guard.py`
- Nuevos tests añadidos a `TestSecurityGuardInjectionAndTraversal`:
  - `test_blocks_shell_injection_on_unrestricted_argument_names`:
    Verifica que argumentos como `target`, `input`, `script`, `query`, `cmd`, `args`, `path`, `container` con payloads maliciosos sean bloqueados.
  - `test_blocks_nested_shell_injection`:
    Verifica el bloqueo en listas y diccionarios anidados.
  - `test_allows_safe_url_query_strings_but_blocks_url_shell_injection`:
    Verifica que URLs con query strings sean aceptadas sin falsos positivos, mientras que delimitadores shell en URLs sean rechazados.

---

## Resultados de Verificación
- **Ruff:** Verificación de linter y formato 100% limpia (`106 files already formatted`).
- **MyPy:** Verificación estricta de tipos exitosa (`Success: no issues found in 106 source files`).
- **Pytest:** 371 pruebas ejecutadas y aprobadas (100% pasando).
