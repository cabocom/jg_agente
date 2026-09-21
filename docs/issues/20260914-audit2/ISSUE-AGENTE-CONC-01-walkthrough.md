# Walkthrough Técnico: [AGENTE-CONC-01] Singletons de Seguridad sin Locks para Inicialización en Corrutinas

## Resumen de Cambios Aplicados

### 1. Implementación de Double-Checked Locking con `threading.Lock`
- **[`app/security/guard.py`](../../../app/security/guard.py):**
  - Declarado `_guard_lock = threading.Lock()`.
  - Protegida la factoría `get_security_guard()` con el patrón de doble comprobación.
- **[`app/security/ssrf.py`](../../../app/security/ssrf.py):**
  - Declarado `_ssrf_lock = threading.Lock()`.
  - Protegida la factoría `get_ssrf_validator()` con el patrón de doble comprobación.
- **[`app/security/audit.py`](../../../app/security/audit.py):**
  - Declarado `_audit_lock = threading.Lock()`.
  - Protegida la factoría `get_security_audit_logger()` con el patrón de doble comprobación.
  - Añadido alias canónico `get_audit_logger = get_security_audit_logger`.
- **[`app/security/__init__.py`](../../../app/security/__init__.py):**
  - Re-exportado `get_audit_logger` en `__all__`.

### 2. Pre-inicialización Determinista en `lifespan` ([`app/main.py`](../../../app/main.py))
- Al inicio de la función `lifespan(app: FastAPI)`:
  ```python
  # 0. Pre-inicialización determinista de singletons de seguridad (AGENTE-CONC-01)
  get_security_audit_logger()
  get_ssrf_validator()
  get_security_guard()
  ```
  Se garantiza que los singletons estén construidos y calientes antes de registrar plugins o iniciar servicios de red.

### 3. Suite de Pruebas de Concurrencia ([`tests/test_security_singletons_concurrency.py`](../../../tests/test_security_singletons_concurrency.py))
- **`test_security_guard_concurrent_initialization_threads`:** 50 hilos concurrentes compitiendo por instanciar `SecurityGuard`; valida identidad estricta (`is` e `id`).
- **`test_security_guard_concurrent_initialization_coroutines`:** 50 tareas asíncronas con context-switch forzado; valida identidad estricta.
- **`test_ssrf_validator_concurrent_initialization_threads`:** 50 hilos concurrentes compitiendo por `SSRFValidator`.
- **`test_ssrf_validator_concurrent_initialization_coroutines`:** 50 corrutinas concurrentes para `SSRFValidator`.
- **`test_audit_logger_concurrent_initialization_threads`:** 50 hilos alternando llamadas entre `get_security_audit_logger()` y `get_audit_logger()`.
- **`test_audit_logger_concurrent_initialization_coroutines`:** 50 corrutinas alternando llamadas concurrentes.
- **`test_lifespan_preinitializes_security_singletons`:** Verifica que tras ejecutarse `lifespan(app)`, los tres singletons existen en memoria y están tipados correctamente.

### 4. Impacto Operacional
- Elimina cualquier posibilidad de condiciones de carrera durante el arranque o picos de tráfico.
- Garantiza la unicidad estricta de las estructuras de datos de seguridad (buffer de auditoría, cachés DNS y guardrails).
