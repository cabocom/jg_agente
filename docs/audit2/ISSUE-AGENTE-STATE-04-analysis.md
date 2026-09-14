# Análisis de Causa Raíz: [AGENTE-STATE-04] Fuga de Memoria por Crecimiento Ilimitado en SecurityAuditLogger

## Diagnóstico Técnico
1. **Acumulación No Acotada en Memoria:**
   En `app/security/audit.py`, la clase `SecurityAuditLogger` inicializaba su historial interno como una lista vacía estándar:
   ```python
   self._history: list[AuditRecord] = []
   ```
   Cada llamada a `record_event()` ejecutaba `self._history.append(record)` sin verificar el tamaño actual de la estructura ni aplicar expulsión de eventos antiguos.

2. **Retención de Referencias a Objetos Complejos:**
   Cada `AuditRecord` almacena campos textuales (`event_type`, `description`), identificadores de usuario/sesión, nivel de riesgo (`SecurityRiskLevel`), marcas de tiempo y un diccionario `metadata` arbitrario. En peticiones complejas o ataques simulados, estos metadatos pueden contener cadenas de texto extensas, volcados de payloads o trazas, multiplicando el impacto de cada registro en memoria.

3. **Ciclo de Vida del Proceso:**
   Al operar como singleton en el contexto global de la aplicación (`_global_audit_logger`), la estructura de datos no se reiniciaba entre peticiones HTTP o ejecuciones de grafos. En procesos de larga duración, la retención indefinida constituía una fuga de memoria (memory leak) estructural.

## Estrategia de Solución
1. **Sustitución por Buffer Circular Acotado (`collections.deque`):**
   Reemplazar la lista interna por una cola de doble extremo acotada:
   ```python
   self._history: deque[AuditRecord] = deque(maxlen=capacity)
   ```
   `collections.deque` gestiona internamente la capacidad fija en tiempo $O(1)$: al llenarse, cualquier nuevo elemento insertado por la derecha (`append`) expulsa automáticamente el elemento más antiguo por la izquierda (política FIFO), manteniendo siempre los eventos de auditoría más recientes sin necesidad de operaciones de truncado manuales ni bloqueos.

2. **Configurabilidad Centralizada:**
   Añadir la variable de entorno `AUDIT_LOG_MAX_HISTORY` en `Settings` (`app/core/config.py`) con valor por defecto de 1000 y validación mínima (`ge=10`), permitiendo a los operadores ajustar la retención en memoria según la capacidad del host.

3. **Compatibilidad Total de la Interfaz:**
   - `get_history()` continúa retornando una lista tipada `list[AuditRecord]` (mediante `list(self._history)`), garantizando inmutabilidad externa y compatibilidad absoluta con todos los consumidores y endpoints.
   - `clear()` invoca `self._history.clear()`, vaciando el buffer circular.
   - Se expone la propiedad de solo lectura `max_history` para facilitar la observabilidad y las aserciones en pruebas unitarias.
