Se ha completado la implementación de **[ISSUE-F08-T01] Cliente de registro con jg_dashboard mediante bootstrap token** en `jg_agente`.

### Resumen de Implementación
1. **Cliente HTTP de Registro (`DashboardRegistrationClient`):**
   - Cliente asíncrono con `httpx` que consume el `AGENT_BOOTSTRAP_TOKEN` en `POST /api/v1/agents/register` (con fallback a `/api/agents/register`).
   - Envío del catálogo de capacidades y metadatos del entorno.
   - Reintentos exponenciales ante caídas de red o respuestas 5xx.
   - Manejo tipado de errores de autenticación (`RegistrationAuthError` ante 401) y conflicto (`RegistrationConflictError` ante 409).
2. **Almacenamiento Local Seguro (`CredentialStore`):**
   - Serialización de credenciales (`AgentCredentials`) en archivo JSON configurable (`settings.CREDENTIALS_FILE`).
   - Restricción automática de permisos en disco a `0600` (lectura/escritura exclusiva del propietario) en sistemas POSIX.
3. **Orquestación en Arranque (`auto_register_agent` y `lifespan`):**
   - Integrado en el ciclo de vida de FastAPI (`app/main.py`).
   - Precedencia de credenciales: variables de entorno (`PERMANENT_AGENT_SECRET`), persistencia local en disco, o consumo de bootstrap token.
   - Modo local/desconectado para pruebas y desarrollo offline cuando no se requiere registro obligatorio.
4. **Verificación Automatizada:**
   - Suite de 13 pruebas unitarias e integradas en `tests/test_registration_client.py`.
   - 100% de las pruebas del repositorio superadas en `./scripts/check.sh` (Ruff, MyPy y Pytest).
5. **Documentación:**
   - Actualización de `README.md`, `PROJECT_CONTEXT.md` (v2.23.0) y generación del cuarteto documental en `docs/issues/ISSUE-F08-T01-*`.

/close
