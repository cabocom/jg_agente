Se ha completado la implementación de **[ISSUE-F08-T03] Bucle de heartbeat periódico hacia jg_dashboard** en `jg_agente`.

### Resumen de Implementación
1. **Servicio en Segundo Plano (`HeartbeatService`):**
   - Implementado en `app/core/heartbeat.py` con métodos `start()`, `stop()`, `run_loop()` y `send_heartbeat()`.
   - Envío de latidos periódicos a `jg_dashboard` cada $N$ segundos (`HEARTBEAT_INTERVAL_SECONDS`, por defecto 30 segundos).
2. **Telemetría y Métricas del Sistema:**
   - Función `collect_system_metrics` que recopila uptime, versión del agente, plataforma, recuento de capacidades activas (`tools_count`, `plugins_count`, `engines_count`) y consumo de memoria del proceso en MB adaptado a Linux y Darwin (`ru_maxrss`).
3. **Resiliencia y Tolerancia a Fallos:**
   - El agente no se interrumpe ni se cae si el Dashboard no responde, sufre cortes de red o timeouts; se capturan los errores y se registran como advertencias.
   - Compatibilidad de endpoints con fallback ante respuestas 404 (`/api/v1/agents/heartbeat` y `/api/agents/heartbeat`).
4. **Ciclo de Vida en FastAPI (`lifespan`):**
   - Arranque automático durante el ciclo `lifespan` tras disponer de credenciales válidas y parada limpia sin fugas de tareas al apagar el servicio.
   - Estado expuesto en `GET /` (`heartbeat_active`, `last_heartbeat_at`).
5. **Verificación Automatizada:**
   - Suite de pruebas completa en `tests/test_heartbeat_service.py` y verificación exitosa con `./scripts/check.sh` (Ruff, MyPy estricto y Pytest).
6. **Documentación:**
   - Actualizados `README.md` (Fase 08 al 100%), `PROJECT_CONTEXT.md` (v2.25.0) y generado el cuarteto documental en `docs/issues/ISSUE-F08-T03-*`.

/close
