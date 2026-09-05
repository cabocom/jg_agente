Se ha completado la implementación de **[ISSUE-F08-T02] Mecanismo de persistencia y recarga de credencial permanente** en `jg_agente`.

### Resumen de Implementación
1. **Recarga Automática en Reinicios:**
   - En arranques posteriores, el agente detecta y recarga de forma transparente el `permanent_agent_secret` y el `agent_id` persistidos en `.agent_credentials.json` o en variables de entorno, sin requerir ningún `AGENT_BOOTSTRAP_TOKEN`.
   - Función `reload_credentials()` para soportar sincronización en memoria y rotación en caliente.
2. **Verificación Activa con Dashboard (`verify_credentials`):**
   - Invocación de validación contra el endpoint de heartbeat del Dashboard (`POST /api/v1/agents/heartbeat` con fallback a `/api/agents/heartbeat`) empleando las credenciales permanentes cargadas.
   - Si el Dashboard valida el acceso (200 OK), el agente arranca con estado `verified=True`.
3. **Invalidación Segura y Resiliencia:**
   - Si el Dashboard rechaza la credencial (HTTP 401/403 por revocación administrativa), se limpia el archivo local y se lanza `RegistrationAuthError`.
   - Si el Dashboard no se encuentra disponible temporalmente por problemas de red, el agente tolera la caída y arranca con `verified=False`.
4. **Telemetría y Estado:**
   - Endpoint raíz `GET /` expone `"registered"`, `"credentials_verified"` y `"dashboard_url"`.
5. **Verificación Automatizada:**
   - Pruebas añadidas en `tests/test_registration_client.py` validando verificación exitosa, revocación 401, tolerancia a fallos de red y recarga en caliente.
   - 100% de las pruebas del repositorio superadas en `./scripts/check.sh` (Ruff, MyPy y Pytest).
6. **Documentación:**
   - Actualización de `README.md`, `PROJECT_CONTEXT.md` (v2.24.0) y generación del cuarteto documental en `docs/issues/ISSUE-F08-T02-*`.

/close
