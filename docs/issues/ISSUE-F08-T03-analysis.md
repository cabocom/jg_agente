# Análisis Técnico: ISSUE-F08-T03 - Bucle de heartbeat periódico hacia jg_dashboard

## 1. Contexto y Objetivos
- **Issue ID:** `ISSUE-F08-T03`
- **Fase:** FASE 08 (Bootstrap del Agente, Registro con Dashboard y Heartbeat)
- **Prioridad:** High
- **Complejidad:** S
- **Dependencias:** `ISSUE-F08-T02`
- **Objetivo:** Implementar una tarea en segundo plano que envíe periódicamente (`POST /api/v1/agents/heartbeat` con fallback a `/api/agents/heartbeat`) telemetría de salud, uso de memoria portable, uptime y estado del agente a `jg_dashboard` cada $N$ segundos (por defecto 30 segundos). Si el Dashboard no responde, se debe registrar una advertencia sin interrumpir ni tumbar el proceso del agente.

## 2. Requerimientos Técnicos
1. **Configuración Dinámica:**
   - `ENABLE_HEARTBEAT: bool = True`
   - `HEARTBEAT_INTERVAL_SECONDS: int = 30`
   - `HEARTBEAT_TIMEOUT_SECONDS: float = 5.0`
2. **Recolección de Métricas Portable (`collect_system_metrics`):**
   - Uptime en segundos basado en el timestamp de arranque.
   - Consumo de memoria en MB (`resource.getrusage(resource.RUSAGE_SELF).ru_maxrss`).
     - Normalización entre Linux (`ru_maxrss / 1024`) y macOS/Darwin (`ru_maxrss / (1024 * 1024)`).
   - Métricas de capacidades registradas (`tools_count`, `plugins_count`, `engines_count`) desde `CapabilityRegistry`.
   - Versión del agente y plataforma del sistema operativo.
3. **Servicio en Segundo Plano (`HeartbeatService`):**
   - Métodos `start()`, `stop()`, `run_loop()`, `send_heartbeat()`.
   - Autenticación mediante cabecera `Authorization: Bearer <PERMANENT_AGENT_SECRET>`.
   - Compatibilidad con endpoints v1 y legado de Dashboard.
   - Resiliencia ante errores de red (`httpx.ConnectError`, `httpx.TimeoutException`, `httpx.NetworkError`): registro de advertencia e incremento de fallos sin levantar excepciones.
   - Detección de rechazo 401/403: registro de error crítico y reseteo de verificación si procede.
4. **Ciclo de Vida de FastAPI (`lifespan`):**
   - Inicialización en startup tras la carga o verificación de credenciales.
   - Cancelación limpia y ordenada (`asyncio.CancelledError`) en shutdown.
   - Exposición en `GET /` de `"heartbeat_active"` y `"last_heartbeat_at"`.

## 3. Estrategia de Pruebas
- Validación unitaria e integradora en `tests/test_heartbeat_service.py`:
  - Recolección de métricas del sistema y normalización de memoria.
  - Envío exitoso 200 OK actualizando marcas temporales y contadores.
  - Compatibilidad de fallback 404.
  - Tolerancia a errores de conexión y timeout sin caídas.
  - Manejo de respuesta no autorizada 401.
  - Ciclo de vida de inicio y parada limpia de la corrutina en segundo plano.
