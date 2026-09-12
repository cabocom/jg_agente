# Project Context: [AGENTE-SEC-03] Evasión de Filtro de Directory Traversal por Falta de Normalización

## Componentes y Capas Afectadas

- **Interceptor de Seguridad (`jg_agente/app/security/guard.py`):**
  - `_BASE_PROTECTED_SYSTEM_PATHS` / `_build_protected_paths()`: Catálogo canónico dinámico que contempla rutas críticas POSIX y Darwin (`/etc`, `/boot`, `/root`, `/var/root`, `/sys`, `/proc`, `/dev`, `/usr`, `/bin`, `/sbin`, `/lib`, `/lib64`, `/var/run`, `/run`, etc.).
  - `_check_directory_traversal_or_protected_path(arg_val: str)`: Lógica canónica de normalización (`os.path.normpath`, `os.path.abspath`, `os.path.realpath`, `urllib.parse.unquote`, `os.path.expanduser`).
  - `SecurityGuard.evaluate`: Inspección canónica de rutas en todos los argumentos de tipo string.

---

## Directrices de Desarrollo y Gobernanza

1. **Prohibición de Comprobaciones Textuales Ingenuas en Rutas de Archivos:**
   - Queda terminantemente prohibido validar rutas del sistema de archivos mediante simples operadores `startswith()` o comprobaciones `in` sobre cadenas sin normalizar.
2. **Normalización Canónica Obligatoria:**
   - Toda validación de rutas debe resolver explícitamente enlaces simbólicos (`realpath`) y secuencias relativas (`normpath`/`abspath`) antes de contrastar con listas de exclusión o inclusión.
3. **Manejo Multiplataforma de Rutas del Sistema:**
   - Las definiciones de rutas protegidas deben contemplar tanto la jerarquía POSIX pura como enlaces canónicos específicos de la plataforma (como `/run` en Linux o `/private` en Darwin).
