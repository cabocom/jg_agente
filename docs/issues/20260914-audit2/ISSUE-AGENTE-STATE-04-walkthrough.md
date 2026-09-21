# Walkthrough Técnico: [AGENTE-STATE-04] Fuga de Memoria por Crecimiento Ilimitado en SecurityAuditLogger

## Resumen de Cambios Aplicados

### 1. Configuración de Capacidad Máxima ([`app/core/config.py`](../../../app/core/config.py))
- Se incorporó el campo de configuración `AUDIT_LOG_MAX_HISTORY`:
  ```python
  AUDIT_LOG_MAX_HISTORY: int = Field(
      default=1000,
      ge=10,
      description="Maximum number of in-memory security audit events retained in the circular buffer before FIFO eviction.",
  )
  ```

### 2. Implementación de Buffer Circular en `SecurityAuditLogger` ([`app/security/audit.py`](../../../app/security/audit.py))
- Se importó `deque` de `collections` y `settings` de `app.core.config`.
- En `__init__(self, max_history: int | None = None)`:
  - Se determina la capacidad a partir de `max_history` explícito o de `settings.AUDIT_LOG_MAX_HISTORY` (con fallback a 1000).
  - Se inicializa el historial acotado:
    ```python
    self._history: deque[AuditRecord] = deque(maxlen=capacity)
    ```
- Se añadió la propiedad `@property def max_history(self) -> int | None: return self._history.maxlen`.
- `get_history()` retorna `list(self._history)` para mantener la inmutabilidad de la estructura interna y garantizar compatibilidad retroactiva.
- `clear()` limpia la deque mediante `self._history.clear()`.

### 3. Suite de Pruebas Automatizadas ([`tests/test_security_audit.py`](../../../tests/test_security_audit.py))
- **`test_bounded_history_capacity_and_fifo_eviction`:**
  Verifica que al instanciar `SecurityAuditLogger(max_history=5)` y registrar 7 eventos consecutivos, la estructura conserve exactamente 5 elementos y haya expulsado automáticamente los 2 eventos más antiguos por política FIFO.
- **`test_default_max_history_from_settings`:**
  Verifica que sin argumento explícito se utilice el valor por defecto configurado en `settings.AUDIT_LOG_MAX_HISTORY` (1000).

### 4. Impacto Operacional
- Se erradica por diseño la fuga de memoria progresiva (OOM) en instancias de producción.
- Inserciones de eventos y expulsiones de registros antiguos con complejidad temporal estricta $O(1)$ sin sobrecarga de recolección de basura ni fragmentación.
