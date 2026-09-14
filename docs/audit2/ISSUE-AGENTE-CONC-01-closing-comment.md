# Cierre de Issue: [AGENTE-CONC-01] Singletons de Seguridad sin Locks para Inicialización en Corrutinas

## Resolución
Se ha resuelto satisfactoriamente la condición de carrera en la inicialización concurrente de los singletons de seguridad de `jg_agente` (Work item [#74](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/74)):

1. **Patrón Double-Checked Locking (DCL) con `threading.Lock`:**
   - Protegidas las factorías `get_security_guard()`, `get_ssrf_validator()` y `get_security_audit_logger()` con cerrojos de exclusión mutua dedicados.
   - Acceso no bloqueante una vez inicializados los singletons, con exclusión garantizada ante llamadas concurrentes desde hilos o corrutinas.

2. **Pre-inicialización Determinista en Lifespan:**
   - Incorporada la inicialización explícita de los tres singletons al inicio del `lifespan` de FastAPI en `app/main.py`.
   - Garantiza que los componentes existan en memoria antes de recibir cualquier estímulo o petición externa.

3. **Alias Canónico:**
   - Añadido el alias `get_audit_logger = get_security_audit_logger` en `app/security/audit.py` y exportado en `app/security/__init__.py`.

4. **Verificación y Pruebas:**
   - Creada la suite `tests/test_security_singletons_concurrency.py` con 7 pruebas de estrés concurrentes (50 hilos y 50 corrutinas concurrentes por singleton).
   - Verificación estática con `ruff check`, `ruff format --check` y `mypy` (109 archivos verificados, 0 errores).
   - Verificación global con `bash check_unit.sh` (424 pruebas de `jg_agente` y 263 pruebas de `jg_dashboard` pasadas exitosamente).
