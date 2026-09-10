# Análisis Técnico: [ISSUE-F08-T02] Mecanismo de persistencia y recarga de credencial permanente

**Issue ID:** ISSUE-F08-T02  
**Fase:** FASE 08 (Bootstrap del Agente, Registro con Dashboard y Heartbeat)  
**Prioridad:** High  
**Complejidad Estimada:** S  
**Dependencias:** ISSUE-F08-T01  

---

## 1. Contexto y Objetivos

Una vez que un agente `jg_agente` ha completado el aprovisionamiento inicial y consumido el `AGENT_BOOTSTRAP_TOKEN` (de un solo uso y 24 horas de vigencia), no debe volver a requerir dicho token en reinicios posteriores.

El objetivo de esta tarea es:
1. Asegurar que en arranques sucesivos el agente cargue directamente su credencial permanente (`permanent_agent_secret` y `agent_id`) desde el almacenamiento persistente local (`.agent_credentials.json`) o desde variables de entorno.
2. Comprobar activamente la validez de la credencial persistida contra el plano de control (`jg_dashboard`) en el arranque (`POST /api/v1/agents/heartbeat` con `X-Agent-ID` y `Authorization: Bearer <permanent_secret>`).
3. Tratar de forma diferenciada las respuestas del Dashboard:
   - **200 OK:** La credencial es válida y el agente queda marcado con `verified=True`.
   - **401/403 Unauthorized:** La credencial fue revocada o invalidada en el Dashboard. Se emite alerta crítica, se elimina la credencial local y se lanza `RegistrationAuthError`.
   - **Fallo de conectividad de red:** El agente es tolerante a particiones de red o arranques offline, permitiendo que el proceso continúe operativo con `verified=False` hasta que el bucle recurrente de heartbeat restablezca el contacto.
4. Proporcionar mecanismos de recarga en memoria (`reload_credentials`) para soportar rotación de credenciales en caliente sin reiniciar el proceso.

---

## 2. Arquitectura de la Solución

### 2.1 Modelo de Datos (`app/models/registration.py`)
- Extensión del modelo `AgentCredentials` con el atributo booleano `verified: bool = False`, que denota si la credencial fue activamente validada con el Dashboard.

### 2.2 Configuración del Agente (`app/core/config.py`)
- Inclusión de `VERIFY_CREDENTIALS_ON_BOOT: bool = True`, permitiendo habilitar o deshabilitar la verificación contra el Dashboard en tiempo de arranque.

### 2.3 Cliente de Verificación (`DashboardRegistrationClient.verify_credentials`)
- Invocación HTTP asíncrona hacia `{dashboard_url}/api/v1/agents/heartbeat` (con fallback a `/api/agents/heartbeat`).
- Envío de cabeceras de autenticación `X-Agent-ID`, `X-Agent-Secret` y `Authorization: Bearer <secret>`.
- Payload de comprobación con métricas fuente (`source: boot_verification`).
- Tipado estricto de excepciones: `RegistrationAuthError` para 401/403 y `DashboardConnectionError` ante caídas de red.

### 2.4 Orquestación y Recarga en Arranque (`auto_register_agent` y `reload_credentials`)
- `auto_register_agent`:
  - Evalúa la presencia de credenciales en disco o entorno.
  - Si existen y `VERIFY_CREDENTIALS_ON_BOOT=True`, invoca `verify_credentials()`.
  - Ante éxito, marca `creds.verified = True`.
  - Ante error 401, limpia el archivo local invocando `store.clear()` para evitar reintentos infinitos con credenciales inválidas.
  - Ante caída de red temporal, registra advertencia y permite continuar el arranque.
- `reload_credentials`:
  - Recarga sincrónica de credenciales desde almacenamiento local actualizando las variables `settings.AGENT_ID` y `settings.PERMANENT_AGENT_SECRET`.

### 2.5 Ciclo de Vida y Telemetría (`app/main.py`)
- Exposición en el estado de FastAPI (`app.state.credentials_verified`) y en la respuesta del endpoint raíz `GET /`:
  - `"registered": bool(credentials)`
  - `"credentials_verified": bool(app.state.credentials_verified)`
  - `"dashboard_url": settings.DASHBOARD_URL`

---

## 3. Criterios de Aceptación Verificados

1. **Reutilización de credencial permanente:** El agente arranca directamente sin requerir bootstrap token si existe el archivo `.agent_credentials.json` o la variable `PERMANENT_AGENT_SECRET`.
2. **Verificación activa con Dashboard:** Al iniciar con credencial existente, se valida contra el endpoint de heartbeat del Dashboard.
3. **Invalidación ante rechazo:** Si el Dashboard devuelve 401, se elimina el archivo local y se aborta con error explícito.
4. **Resiliencia de red:** Si el Dashboard está caído temporalmente en boot, el agente no aborta y arranca en modo tolerante.
