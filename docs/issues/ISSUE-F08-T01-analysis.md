# Análisis Técnico: [ISSUE-F08-T01] Cliente de registro con jg_dashboard mediante bootstrap token

**Issue ID:** ISSUE-F08-T01  
**Fase:** FASE 08 (Bootstrap del Agente, Registro con Dashboard y Heartbeat)  
**Prioridad:** Critical  
**Complejidad Estimada:** M  
**Dependencias:** ISSUE-F01-T01  

---

## 1. Contexto y Objetivos

En el ecosistema jG, el aprovisionamiento de nuevos agentes se rige por un esquema **Zero-Trust**:
1. Un operador o administrador genera en el Control Plane (`jg_dashboard`) un token de un solo uso con caducidad estricta (`bootstrap_token`, TTL de 24 horas).
2. El agente `jg_agente` arranca inyectando `AGENT_BOOTSTRAP_TOKEN` y `DASHBOARD_URL`.
3. Durante el arranque (`lifespan`), el agente contacta con el Dashboard en `POST /api/v1/agents/register` presentando el token y su catálogo de capacidades.
4. El Dashboard valida el token, lo marca como consumido y responde con un `permanent_agent_secret` y el `agent_id` definitivo.
5. El agente almacena localmente de forma segura las credenciales permanentes (restringiendo permisos en disco a `0600`) y actualiza su estado interno.
6. En rearranques posteriores, el agente detecta las credenciales persistidas y arranca directamente sin requerir un nuevo bootstrap token.

El objetivo de esta tarea es implementar este cliente HTTP asíncrono, la persistencia local protegida y la orquestación en el ciclo de vida del agente.

---

## 2. Arquitectura de la Solución

### 2.1 Modelos de Contrato (`app/models/registration.py`)
- `AgentRegistrationPayload`: payload serializado que incluye `bootstrap_token`, `agent_name`, `version`, `capabilities` y `metadata`.
- `AgentRegistrationResponse`: respuesta estructurada del Dashboard que contiene `agent_id`, `name`, `status`, `permanent_secret` y `registered_at`.
- `AgentCredentials`: modelo de credenciales persistidas en disco (`agent_id`, `permanent_secret`, `agent_name`, `dashboard_url`, `registered_at`).

### 2.2 Almacenamiento Seguro de Credenciales (`CredentialStore`)
- Persistencia en archivo JSON configurable mediante `settings.CREDENTIALS_FILE` (por defecto `.agent_credentials.json`).
- Aplicación de permisos restrictivos `0o600` (lectura/escritura exclusiva del propietario) en entornos POSIX para proteger el secreto permanente.
- Métodos auxiliares `save()`, `load()`, `exists()` y `clear()` tolerantes a fallos y archivos corruptos.

### 2.3 Cliente HTTP de Registro (`DashboardRegistrationClient`)
- Implementado sobre `httpx.AsyncClient` con soporte para inyección de transporte (`transport`) para testing sin sockets reales.
- Reintentos exponenciales automáticos ante caídas transitorias de red o respuestas 5xx del Dashboard.
- Manejo explícito y diferenciado de errores:
  - `RegistrationAuthError` ante respuestas HTTP 401 (token inválido o expirado).
  - `RegistrationConflictError` ante respuestas HTTP 409 (token ya consumido).
  - `DashboardConnectionError` ante fallos persistentes de red o timeout.
- Mecanismo de fallback: si `/api/v1/agents/register` responde 404, reintenta automáticamente con `/api/agents/register`.

### 2.4 Orquestación en el Ciclo de Vida (`auto_register_agent` y `lifespan`)
- En `app/main.py`, la función `lifespan` ejecuta `auto_register_agent` tras la inicialización de capacidades del `CapabilityRegistry`.
- Precedencia de credenciales:
  1. Si `PERMANENT_AGENT_SECRET` ya está definido en el entorno, se omite el registro.
  2. Si existe un archivo de credenciales válido en disco, se cargan y sincronizan en memoria.
  3. Si no hay credenciales pero se detecta `AGENT_BOOTSTRAP_TOKEN`, se ejecuta el registro HTTP y se guardan las credenciales.
  4. Si no hay token ni credenciales y `REQUIRE_DASHBOARD_REGISTRATION=False`, se permite el funcionamiento en modo local/standalone para pruebas y desarrollo desconectado.

---

## 3. Criterios de Aceptación Verificados

1. **Invocación de registro:** Al arrancar con `AGENT_BOOTSTRAP_TOKEN`, el agente realiza `POST /api/v1/agents/register` con la cabecera `Authorization: Bearer <token>`.
2. **Recepción y persistencia de secreto permanente:** El `permanent_secret` recibido se guarda en disco con permisos seguros.
3. **Idempotencia y omisión en rearranques:** Si el archivo local existe o el secreto está en variables de entorno, no se consume token adicional.
4. **Resiliencia ante errores:** Excepciones claras ante tokens 401 y 409, y reintentos ante caídas transitorias.
