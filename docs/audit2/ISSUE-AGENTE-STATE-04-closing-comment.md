# Cierre de Issue: [AGENTE-STATE-04] Fuga de Memoria por Crecimiento Ilimitado en SecurityAuditLogger

## Resolución
Se ha resuelto satisfactoriamente la fuga de memoria por retención ilimitada en el historial de auditoría de seguridad de `jg_agente` (Work item [#73](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/73)):

1. **Buffer Circular Acotado con Política FIFO:**
   - Se reemplazó la lista acumulativa no acotada `self._history: list[AuditRecord] = []` por una cola circular de tamaño fijo `collections.deque(maxlen=capacity)` en `app/security/audit.py`.
   - Cuando se alcanza la capacidad máxima configurada, los registros más antiguos son automáticamente desalojados de forma transparente en tiempo constante $O(1)$ sin bloquear el bucle de eventos.

2. **Configuración Centralizada en Entorno:**
   - Se añadió la variable de configuración `AUDIT_LOG_MAX_HISTORY: int = Field(default=1000, ge=10)` en `app/core/config.py`.
   - El registrador permite además inyección explícita de `max_history` para pruebas o instancias especializadas y expone la propiedad `@property def max_history`.

3. **Compatibilidad y Estabilidad:**
   - `get_history()` retorna `list(self._history)` preservando la compatibilidad completa con el resto del agente y el dashboard.
   - `clear()` reinicia el buffer de forma atómica.

4. **Verificación y Pruebas:**
   - Nuevos tests añadidos en `tests/test_security_audit.py` comprobando expulsión FIFO y enlace con la configuración centralizada.
   - Verificación estática con `ruff check`, `ruff format --check` y `mypy` (108 archivos analizados, 0 errores).
   - Verificación global con `bash check_unit.sh` (417 pruebas unitarias de `jg_agente` y 263 de `jg_dashboard` pasadas exitosamente).
