## Resolución y Cierre de Issue [AGENTE-STATE-01]

### Resumen de la Corrección
Se ha eliminado la persistencia *best-effort* y el enmascaramiento de fallos de base de datos (`persistence.status = "degraded"` con HTTP 200 OK) en `jg_agente`:

1. **Reintentos con Backoff Exponencial (`app/api/executions.py`):**
   - Se implementó `_persist_with_retry` con 3 reintentos y pausas progresivas (0.2s, 0.4s, 0.8s), garantizando tolerancia ante fallos transitorios de PostgreSQL.
2. **Propagación Explícita de Error (HTTP 500):**
   - Si la persistencia falla tras agotar los reintentos, el endpoint responde con `HTTP 500 Internal Server Error`, alertando inmediatamente al Dashboard y evitando la pérdida silenciosa de registros.
3. **Respaldo de Emergencia en Disco (Emergency Spooling):**
   - Ante fallo fatal de base de datos, el estado y las trazas de la ejecución se vuelcan a disco local en `data/emergency_executions/<execution_id>.json` antes de emitir el error HTTP 500.
4. **Liberación de Sesiones (`AGENTE-STATE-03`):**
   - Desacoplada la sesión de larga duración en `trigger_execution`, previniendo la saturación del pool de conexiones.
5. **Cobertura de Pruebas:**
   - 9 casos de prueba automatizados en `tests/test_persistence_propagation.py` pasando al 100%.

**Commits asociados:**
- `fix(persistence): resolver AGENTE-STATE-01 y AGENTE-STATE-03 con reintentos exponenciales, spooling de emergencia y HTTP 500`
