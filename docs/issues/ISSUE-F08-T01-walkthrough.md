# Walkthrough: [ISSUE-F08-T01] Cliente de registro con jg_dashboard mediante bootstrap token

**Issue ID:** ISSUE-F08-T01  
**Fase:** FASE 08 (Bootstrap del Agente, Registro con Dashboard y Heartbeat)  
**Fecha:** 5 de septiembre de 2026  

---

## 1. Resumen de Cambios Realizados

Se ha implementado el cliente de registro con bootstrap token y la persistencia de credenciales en `jg_agente`:

1. **Configuración del Agente (`app/core/config.py`):**
   - Incorporadas variables: `DASHBOARD_URL`, `AGENT_BOOTSTRAP_TOKEN`, `PERMANENT_AGENT_SECRET`, `CREDENTIALS_FILE`, `AGENT_NAME`, `DASHBOARD_REGISTRATION_TIMEOUT`, `DASHBOARD_REGISTRATION_RETRIES` y `REQUIRE_DASHBOARD_REGISTRATION`.

2. **Modelos Pydantic (`app/models/registration.py` y `app/models/__init__.py`):**
   - Definidos `AgentRegistrationPayload`, `AgentRegistrationResponse` y `AgentCredentials`.

3. **Almacenamiento Local y Cliente HTTP (`app/core/registration.py`):**
   - `CredentialStore`: guardado seguro con permisos `0600` en sistemas POSIX y carga tolerante a fallos.
   - `DashboardRegistrationClient`: cliente asíncrono con `httpx`, reintentos exponenciales, fallback de endpoints (`/api/v1/agents/register` y `/api/agents/register`) y tipado de errores (`RegistrationAuthError`, `RegistrationConflictError`, `DashboardConnectionError`).
   - `auto_register_agent`: función de decisión en boot que evalúa precedencia de credenciales en variables de entorno, disco local o aprovisionamiento con bootstrap token.

4. **Integración en Arranque (`app/main.py`):**
   - En el gestor `lifespan`, se invoca `auto_register_agent` tras la inicialización de plugins y capacidades.
   - Se almacena el resultado en `app.state.credentials` y se expone el estado de registro en el endpoint raíz `GET /`.

5. **Suite de Pruebas Automatizadas (`tests/test_registration_client.py`):**
   - 13 pruebas unitarias e integradas cubriendo persistencia segura (permisos 0600), registro HTTP exitoso, fallback 404, errores 401/409, reintentos 503, caídas de conexión y comportamiento standalone.

---

## 2. Verificación de Funcionamiento

Se ejecutó la suite completa de calidad:

```bash
./scripts/check.sh
```

**Resultado:**
- Formateador y linter Ruff: 100% conforme en los 69 archivos de código fuente.
- Tipado estricto MyPy: sin inconsistencias ni advertencias.
- Suite de pruebas Pytest: 231 tests unitarios e integrados pasando satisfactoriamente.

---

## 3. Próximos Pasos

Continuar con la **FASE 08** de `jg_agente`:
- **ISSUE-F08-T02:** Persistencia de credencial permanente del agente y gestión de ciclo de vida de credenciales.
- **ISSUE-F08-T03:** Bucle de heartbeat periódico hacia `jg_dashboard`.
