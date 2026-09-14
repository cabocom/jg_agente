# Análisis de Causa Raíz: [AGENTE-CONC-01] Singletons de Seguridad sin Locks para Inicialización en Corrutinas

## Diagnóstico Técnico
1. **Condición de Carrera en Inicialización Perezosa (Check-Then-Act):**
   Las funciones `get_security_guard()`, `get_ssrf_validator()` y `get_security_audit_logger()` implementaban el antipatrón de inicialización perezosa sin exclusión mutua:
   - Hilo/Corrutina A comprueba `_default_instance is None` (True).
   - Context switch o ejecución concurrente: Hilo/Corrutina B comprueba `_default_instance is None` (True).
   - Ambos hilos instancian la clase `Cls()`.
   - La última asignación sobrescribe la variable global, dejando huérfana la primera instancia y perdiendo cualquier estado o referencia asociada.

2. **Dependencias Circulares/Cruzadas en Constructores:**
   `SecurityGuard.__init__` depende a su vez de `get_security_audit_logger()` y `get_ssrf_validator()`. Si la inicialización de `SecurityGuard` disparaba la creación concurrente de las otras dos dependencias sin cerrojos, se amplificaba la probabilidad de inconsistencias de estado y condiciones de carrera anidadas.

3. **Incompatibilidad de `asyncio.Lock` con Firmas Síncronas:**
   Las funciones factory `get_security_guard()`, etc., son funciones puramente síncronas (`def ... -> Cls:`) utilizadas a lo largo de constructores síncronos (`__init__`), callbacks y rutas. Requerir `asyncio.Lock` obligaría a convertir todas las factorías a corrutinas asíncronas (`async def`), rompiendo firmas y contratos en todo el codebase.

## Estrategia de Solución
1. **Double-Checked Locking (DCL) con `threading.Lock`:**
   El patrón de doble comprobación respaldado por un cerrojo a nivel de hilo (`threading.Lock`) proporciona seguridad de concurrencia completa:
   - Comprobación rápida sin bloqueo: `if _instance is None:`
   - Adquisición de cerrojo exclusivo: `with _lock:`
   - Segunda comprobación protegida: `if _instance is None: _instance = Cls()`
   Esto elimina la penalización de rendimiento en llamadas subsiguientes una vez inicializado y garantiza que ningún hilo ni corrutina pueda crear instancias duplicadas.

2. **Pre-inicialización Determinista en `lifespan`:**
   En `app/main.py`, durante la fase de arranque de FastAPI y antes de registrar plugins o aceptar tráfico HTTP, se invocan explícitamente:
   ```python
   get_security_audit_logger()
   get_ssrf_validator()
   get_security_guard()
   ```
   Esto asegura que todas las estructuras estén completamente instanciadas y disponibles en memoria desde el milisegundo cero.

3. **Alias Canónico Retrocompatible:**
   Se definió y exportó el alias `get_audit_logger = get_security_audit_logger` para asegurar máxima consistencia estilística y compatibilidad.
