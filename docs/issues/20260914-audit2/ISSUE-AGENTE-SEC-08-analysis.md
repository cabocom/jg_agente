# Análisis Técnico - Issue [AGENTE-SEC-08]

**Issue:** [jg_agente#64](https://gitlab.com/javiergalvez-ia/jg_agente/-/work_items/64)  
**Título:** [AGENTE-SEC-08] Fuga de Información Sensible e Interna en Respuestas de Error HTTP  
**Severidad:** 🟡 MEDIO  
**CWE:** CWE-209 (Generation of Error Message Containing Sensitive Information)  
**Ubicación:** `jg_agente/app/api/executions.py:445-490`  

---

## 1. Contexto y Causa Raíz

En el pipeline de ejecución del agente (`execute_graph_pipeline` dentro de `app/api/executions.py`), los errores no controlados durante la invocación del grafo cognitivo eran capturados mediante un bloque genérico:

```python
except Exception as exc:
    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    logger.exception("Error no controlado durante la ejecución del grafo: %s", exc)
    agent_output = AgentOutput(
        execution_id=input_data.execution_id,
        thread_id=thread_id,
        status=ExecutionStatus.FAILED,
        response=f"Error durante la ejecución del agente: {exc}",
        execution_time_ms=elapsed_ms,
        error=str(exc),
        requires_approval=False,
        metadata=input_data.metadata,
        completed_at=datetime.now(UTC),
    )
```

### Vulnerabilidad Identificada

1. **Fuga de Excepciones sin Sanitizar (CWE-209):**
   Al asignar `response=f"Error durante la ejecución del agente: {exc}"` y `error=str(exc)`, los mensajes internos de error de Python se enviaban directamente en la respuesta HTTP JSON al cliente.
2. **Exposición de Metadatos y Rutas de Sistema:**
   Las cadenas generadas por librerías subyacentes (tales como `asyncpg`, `sqlalchemy`, `httpx`, o excepciones personalizadas del motor de grafo) frecuentemente contienen:
   - Rutas absolutas del sistema de archivos (`/Users/...`, `/app/...`, `/opt/...`).
   - Nombres de módulos internos, funciones y números de línea.
   - Direcciones IP internas, sockets Unix o nombres de host de la red privada (`10.0.x.x`, puertos de bases de datos).
   - Fragmentos de consultas SQL, parámetros de conexión o credenciales formateadas en URIs de excepción.
3. **Fugas en Metadatos de Persistencia:**
   En los bloques de degradación de persistencia (`PersistenceStatus.DEGRADED`), se asignaba `error=str(db_err)`, exponiendo mensajes directos del driver de base de datos (`socket.gaierror`, `asyncpg.CannotConnectNowError`) hacia `agent_output.metadata["persistence"]["error"]`.

---

## 2. Impacto de Seguridad

- **Reconocimiento y Huella Digital:** Un atacante externo o usuario no privilegiado puede forzar excepciones malformadas para descubrir la topología interna del servidor, versiones de dependencias, rutas del sistema y arquitectura de base de datos.
- **Incumplimiento de Estándares Seguros:** Contraviene las directrices OWASP y CWE-209 sobre no exponer mensajes técnicos ni trazas de excepciones a clientes finales.

---

## 3. Solución Implementada

1. **Mensajes Genéricos Seguros con Identificador de Incidencia:**
   - Se definió la constante `GENERIC_EXECUTION_ERROR_MSG`:
     ```python
     GENERIC_EXECUTION_ERROR_MSG = (
         "Error interno durante la ejecución del agente (ID de incidencia: {execution_id}). "
         "Por favor, consulte los registros del sistema."
     )
     ```
   - Tanto `agent_output.response` como `agent_output.error` utilizan identificadores de incidencia vinculados al `execution_id`, evitando revelar detalles técnicos al cliente.

2. **Registro Interno Detallado (Defense-in-Depth):**
   - El stacktrace técnico completo se mantiene preservado internamente en los logs del servidor mediante `logger.exception(...)` y en la base de datos relacional para auditoría de administradores (`CoreExecution.error_msg`).

3. **Sanitización de Metadatos de Persistencia:**
   - Se reemplazó `error=str(db_err)` y `error=str(p_err)` por la constante segura `GENERIC_PERSISTENCE_ERROR_MSG = "Fallo en la persistencia de ejecución. Consulte los registros del servidor."` en todos los bloques `PersistenceStatus.DEGRADED`.

4. **Pruebas Automatizadas:**
   - Añadida prueba en `test_api_executions_trigger.py` (`test_trigger_execution_uncaught_error_sanitized_response`) simulando una excepción con cadenas de conexión y rutas internas, verificando que la respuesta HTTP no filtre ninguna información sensible y retorne el mensaje genérico con el ID de incidencia.
