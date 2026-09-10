# Walkthrough: [ISSUE-F08-T02] Mecanismo de persistencia y recarga de credencial permanente

**Issue ID:** ISSUE-F08-T02  
**Fase:** FASE 08 (Bootstrap del Agente, Registro con Dashboard y Heartbeat)  
**Fecha:** 5 de septiembre de 2026  

---

## 1. Resumen de Cambios Realizados

Se ha implementado el mecanismo de persistencia, recarga y verificación activa de credenciales permanentes en `jg_agente`:

1. **Configuración de Verificación (`app/core/config.py`):**
   - Incorporada la opción `VERIFY_CREDENTIALS_ON_BOOT: bool = True`.

2. **Modelo de Credenciales (`app/models/registration.py`):**
   - Añadido el atributo `verified: bool = False` en `AgentCredentials`.

3. **Cliente de Verificación y Recarga (`app/core/registration.py`):**
   - Implementado `verify_credentials(agent_id, permanent_secret)` en `DashboardRegistrationClient`, invocando el endpoint de heartbeat del Dashboard con las cabeceras de autenticación requeridas.
   - Actualizado `auto_register_agent()` para verificar credenciales existentes en variables de entorno o disco, marcando `verified=True` ante éxito, tolerando desconexiones de red, e invalidando credenciales locales ante rechazos 401 del Dashboard.
   - Implementada la función `reload_credentials(settings)` para permitir la recarga y sincronización de credenciales en caliente.

4. **Integración en Lifespan y Endpoint Raíz (`app/main.py`):**
   - Almacenado `credentials_verified` en el estado de FastAPI (`app.state.credentials_verified`).
   - El endpoint `GET /` expone los campos `"registered"`, `"credentials_verified"` y `"dashboard_url"`.

5. **Suite de Pruebas Automatizadas (`tests/test_registration_client.py`):**
   - Pruebas añadidas para:
     - Verificación 200 OK con el Dashboard.
     - Detección de credencial revocada (HTTP 401) y limpieza del archivo local de credenciales.
     - Tolerancia y resiliencia ante caídas de red del Dashboard durante el boot.
     - Recarga en memoria de credenciales persistidas con `reload_credentials()`.

---

## 2. Verificación de Funcionamiento

Se ejecutó la suite completa de verificación:

```bash
./scripts/check.sh
```

**Resultado:**
- Formateo y linter Ruff: 100% conforme en los 69 archivos del proyecto.
- Tipado estricto MyPy: sin inconsistencias en todos los archivos.
- Suite Pytest: 238 tests pasando en verde (incluyendo las 7 nuevas pruebas de verificación y recarga).

---

## 3. Próximos Pasos

Continuar con la **FASE 08** de `jg_agente`:
- **ISSUE-F08-T03:** Bucle periódico de heartbeat hacia Dashboard con telemetría de ejecuciones y reconexión automática.
