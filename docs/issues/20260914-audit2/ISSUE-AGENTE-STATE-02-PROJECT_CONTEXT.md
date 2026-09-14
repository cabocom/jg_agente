# Contexto del Proyecto: [AGENTE-STATE-02] Degradación Silenciosa de DualPostgresSaver a Memoria y Fuga de Conexiones

## Descripción del Entorno
- **Componente:** `jg_agente` (Execution Plane)
- **Capa Afectada:** Checkpointer de LangGraph (`app/core/checkpointer.py`), Ciclo de vida FastAPI (`app/main.py`), Telemetría y Monitoreo (`app/api/telemetry.py`)
- **Base de Datos / Pool:** PostgreSQL / `psycopg_pool.ConnectionPool`
- **Severidad:** 🟡 MEDIO

## Contexto Operativo
LangGraph se apoya en checkpointers para congelar el estado del grafo en puntos de control (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`), permitiendo:
1. Pausar ejecuciones en puertas de confirmación humana (HITL - Human-in-the-Loop) y reanudarlas con seguridad en un momento arbitrario posterior.
2. Recuperar el estado tras reinicios imprevistos de los contenedores de ejecución o workers.
3. Garantizar idempotencia e inspección temporal del flujo de razonamiento y ejecución de herramientas.

En `jg_agente`, la clase `DualPostgresSaver` extiende `PostgresSaver` de LangGraph utilizando un pool de conexiones `psycopg_pool.ConnectionPool` para soportar acceso síncrono y asíncrono (`ainvoke`).

## Problema Detectado
1. **Degradación silenciosa sin alarma crítica ni reintentos:**
   Si al arrancar el agente PostgreSQL no estaba disponible inmediatamente (retraso de inicio, red temporalmente inaccesible), `get_checkpointer()` capturaba la excepción con un simple `logger.warning` y conmutaba silenciosamente a `MemorySaver()`.
   El servicio arrancaba con normalidad, `/health` reportaba `checkpointer: ready` con HTTP 200, y Docker consideraba el contenedor como `healthy`.
   Al reiniciar el contenedor, cualquier ejecución pendiente de aprobación HITL o checkpoint se destruía irrevocablemente.
2. **Fuga de descriptores y conexiones (Connection Leaks):**
   `DualPostgresSaver` no exponía un método `.close()` para finalizar el pool de conexiones `ConnectionPool`. Además, el lifespan de FastAPI en `app/main.py` no precalentaba ni almacenaba la instancia de checkpointer, y nunca invocaba el cierre explícito de conexiones durante el apagado del servicio (`shutdown`).
