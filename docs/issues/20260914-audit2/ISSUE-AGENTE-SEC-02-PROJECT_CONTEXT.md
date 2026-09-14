# Project Context: [AGENTE-SEC-02] Evasión de Filtro de Inyección Shell por Restricción de Nombre de Argumentos

## Componentes y Capas Afectadas

- **Interceptor de Seguridad (`jg_agente/app/security/guard.py`):**
  - `_extract_string_arguments(args, parent_key)`: Función utilitaria recursiva para extraer argumentos en colecciones anidadas (dicts, lists, tuples, sets).
  - `SHELL_INJECTION_PATTERN`: Expresión regular universal aplicada a todos los argumentos de tipo string.
  - `URL_SHELL_INJECTION_PATTERN`: Expresión regular adaptada para URLs HTTP/HTTPS (`http://`, `https://`) que permite parámetros válidos de consulta (`&` y comillas) pero bloquea caracteres de escape e inyección shell (`;`, `` ` ``, `$`, `|`, `>`, `<`, `\n`, `\r`, `\\`).
  - `SecurityGuard.evaluate`: Validación desacoplada de la nomenclatura de parámetros.

---

## Directrices de Desarrollo y Gobernanza

1. **Inspección Universal de Argumentos de Entrada:**
   - La validación de inyección de comandos o metacaracteres no debe basarse en listas cerradas de nombres de parámetros (e.g. `command`, `name`, `service`, `host`). Debe aplicarse transversalmente a todas las entradas de tipo string recibidas por cualquier herramienta o plugin.
2. **Tratamiento Jerárquico de Payloads:**
   - Todo validador de seguridad en el gateway del agente debe analizar estructuras de datos anidadas de forma recursiva antes de conceder la decisión de ejecución (`PolicyDecision.ALLOW`).
3. **Manejo Contextual de Tipos de Entrada:**
   - Entradas especializadas como URLs deben validarse preservando su sintaxis legítima (query strings con `&`) mientras se mantienen bloqueados los vectores de control de flujo del intérprete de comandos del sistema operativo.
