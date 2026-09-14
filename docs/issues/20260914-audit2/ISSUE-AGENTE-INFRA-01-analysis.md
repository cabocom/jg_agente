# Análisis de Causa Raíz: [AGENTE-INFRA-01] Ausencia de Workers en Uvicorn y Versión Menor no Fijada en Dockerfile

## Diagnóstico Técnico
1. **Riesgo de Cadena de Suministro por Tags Flotantes:**
   En Docker, las etiquetas que solo especifican versión mayor o menor intermedia (ej. `python:3.12-slim`) son tags mutables. En cada ejecución de `docker build`, la imagen base puede incorporar silenciosamente parches del sistema operativo Debian subyacente o de la distribución de Python que alteren comportamientos o introduzcan regresiones.
   La buena práctica de seguridad y reproducibilidad exige fijar al menos la versión menor completa (`python:3.12.6-slim`).

2. **Monoproceso y Cuello de Botella del GIL:**
   El comando `uvicorn app.main:app` sin especificar `--workers` crea un único proceso trabajador. Aunque el bucle de eventos asíncrono de `asyncio` atiende múltiples sockets I/O concurrentemente, cualquier operación síncrona o bloqueante (cálculo de hashes SHA-256 en autenticación de control plane, serializaciones de LangGraph checkpoints o procesamiento de texto) detiene a todos los demás clientes.
   Al habilitar múltiples workers, Uvicorn utiliza el proceso maestro para distribuir las conexiones entrantes mediante socket reuse o balanceo a nivel de kernel entre distintos procesos de Python independientes, aprovechando los múltiples cores del procesador.

3. **Manejo de Señales POSIX con `exec`:**
   Al parametrizar variables de entorno en el `CMD` de Docker (`${UVICORN_WORKERS:-2}`), es necesario invocar la shell (`sh -c`). Si no se utiliza `exec`, el proceso principal PID 1 es la shell `/bin/sh` y no Uvicorn, impidiendo que `SIGTERM` llegue a Uvicorn y provocando que `docker stop` espere 10 segundos antes de forzar `SIGKILL`, rompiendo el ciclo de apagado ordenado del `lifespan`.
   Con `exec uvicorn ...`, Uvicorn reemplaza a `/bin/sh` como PID 1 y gestiona el apagado limpio de inmediato.

## Estrategia de Solución
1. **Fijación Determinista:**
   Fijar la imagen base a `python:3.12.6-slim` tanto en `builder` como en `runner`.
2. **Definición de `UVICORN_WORKERS`:**
   Declarar `UVICORN_WORKERS=2` en `ENV` de `Dockerfile` y exponer `UVICORN_WORKERS: int = Field(default=2, ge=1)` en `Settings` (`app/core/config.py`).
3. **Comando de Arranque Robusto:**
   Configurar:
   ```dockerfile
   CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
   ```
4. **Soporte en Docker Compose:**
   Parametrizar `UVICORN_WORKERS: ${UVICORN_WORKERS:-2}` en los servicios de agente en los manifiestos de Compose.
