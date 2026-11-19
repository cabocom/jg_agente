> ⚠️ **Nota:** Este repositorio es un *mirror* público sincronizado automáticamente desde [GitLab](https://gitlab.com/javiergalvez-ia). El desarrollo activo, pipelines CI/CD, *issues* y discusiones técnicas se gestionan en https://gitlab.com/javiergalvez-ia

<div align="center">

# 🤖 `jg_agente`

### Enterprise Cognitive Agent Runtime for Private & Secure Environments
*Motor Autónomo de Ejecución Cognitiva, Gobernanza HITL y Reversibilidad Transaccional*

[![GitLab CI/CD](https://img.shields.io/badge/GitLab_CI-Pipeline_Passing-108548?style=flat-square&logo=gitlab&logoColor=white)](https://gitlab.com/javiergalvez-ia/jg_agente)
[![Mirror to GitHub](https://img.shields.io/badge/GitHub-Mirror_Active-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/cabocom/jg_agente)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/Orchestrator-LangGraph-FF4F00?style=flat-square&logo=diagram-next&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Security Guard](https://img.shields.io/badge/Security-SSRF_%26_DNS_Pinning-crimson?style=flat-square&logo=shield&logoColor=white)](#1-visión-general-y-propósito)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=flat-square)](https://github.com/astral-sh/ruff)
[![Architecture](https://img.shields.io/badge/Architecture-Clean_%26_Hexagonal-blueviolet?style=flat-square)](#1-visión-general-y-propósito)

</div>

---

## 1. Visión General y Propósito

`jg_agente` es el plano de ejecución autónomo (**Execution Plane**) del ecosistema agéntico jG. Está concebido como un microservicio privado, asíncrono y de alto rendimiento construido sobre [FastAPI](https://fastapi.tiangolo.com/) y [LangGraph](https://github.com/langchain-ai/langgraph), diseñado para ejecutarse en **redes privadas, infraestructuras on-premise, nubes soberanas o entornos de alta conformidad (air-gapped)** sin exposición pública directa a Internet.

A diferencia de chatbots convencionales o cadenas lineales de automatización, `jg_agente` implementa:
1. **Ensamblado Dinámico Radical:** La máquina de estados LangGraph se compila en el arranque inspeccionando el catálogo de capacidades (`CapabilityRegistry`) sin referencias fijas ni acoplamiento a dominios específicos.
2. **Gobernanza Human-In-The-Loop (HITL) Nativa:** Pausa transparente del grafo mediante `interrupt()` y persistencia transaccional de checkpoints ante operaciones de riesgo `HIGH` o `CRITICAL`.
3. **Reversibilidad y Compensación Automática:** Motor de rollback que ejecuta compensadores (`tool.rollback_func`) en orden cronológico inverso ante fallos detectados por el motor de verificación (`VerifierEngine`).
4. **Seguridad Perimetral y Zero-Trust:** Mitigación activa contra SSRF y DNS Rebinding mediante **DNS Pinning a nivel TCP**, desinfección universal contra Directory Traversal e inyecciones de comandos shell, y firmas criptográficas **HMAC-SHA256**.

### Documentación Técnica Modular
Estructurada en múltiples idiomas bajo [`docs/`](docs/README.md):
- 🇪🇸 **Español (SSOT):**
  - [01. Arquitectura del Runtime](docs/es/01_architecture.md) — Topología de red, componentes core y aislamiento.
  - [02. Grafo Cognitivo y Máquina de Estados](docs/es/02_cognitive_graph.md) — Flujo reflexivo de 10 nodos y guardarraíles.
  - [03. Seguridad, Aislamiento de Red y Sandboxing](docs/es/03_security_sandboxing.md) — SecurityGuard, anti-SSRF y DNS Pinning.
  - [04. Persistencia, Estado y Checkpointing](docs/es/04_persistence_state.md) — DualPostgresSaver, esquema relacional y modo degradado.
  - [05. Ciclo de Vida y Ecosistema de Plugins](docs/es/05_plugin_lifecycle.md) — Descubrimiento dinámico y gestión de dependencias.
  - [06. Referencia de API REST Privada](docs/es/06_api_reference.md) — Especificación de endpoints, esquemas I/O y códigos HTTP.
  - [07. Modos de Funcionamiento, Topologías y Registro](docs/es/07_operational_modes.md) — Standalone (Telegram/WhatsApp), Clúster con Dashboard y registro Zero-Trust.
- 🇬🇧 **English (Reference):**
  - [01. Runtime Architecture](docs/en/01_architecture.md)

---

## 2. Topología del Grafo Cognitivo

El runtime compila dinámicamente un `StateGraph` de 10 nodos según las capacidades registradas:

```text
                  [Entrada: AgentInput]
                            │
                            ▼
               ┌───────────────────────────┐
               │   1. Telemetría (observe) │ ──► (Condicional: si hay ObserverEngine)
               └─────────────┬─────────────┘
                             ▼
               ┌───────────────────────────┐
         ┌───► │  2. Inferencia (reason)   │ ◄─────────────────────────────────────────┐
         │     └─────────────┬─────────────┘                                           │
         │                   ▼                                                         │
         │     ┌───────────────────────────┐                                           │
         │     │ 3. Formulación Plan (plan)│ ──► (Condicional: si hay PlannerEngine)   │
         │     └─────────────┬─────────────┘                                           │
         │                   ▼                                                         │
         │     ┌───────────────────────────┐                                           │
         │     │  4. Riesgo (risk_assess)  │ ──► (Condicional: Tools HIGH/CRITICAL)    │
         │     └─────────────┬─────────────┘                                           │
         │                   │                                                         │
         │      ¿Riesgo >= HIGH o Mutación?                                            │
         │     ┌─────────────┴─────────────┐                                           │
         │[SÍ] ▼                           ▼ [NO]                                      │
         │ ┌───────────────────┐           │                                           │
         │ │ Pausa Checkpoint  │           │                                           │
         │ │ (human_approval)  │           │                                           │
         │ └─────────┬─────────┘           │                                           │
         │           │ (Resume HITL)       │                                           │
         │           └─────────────┬───────┘                                           │
         │                         ▼                                                   │
         │     ┌───────────────────────────┐                                           │
         │     │  5. Ejecución (execute)   │ ──► (Sandbox + Timeouts + SecurityGuard)  │
         │     └─────────────┬─────────────┘                                           │
         │                   ▼                                                         │
         │     ┌───────────────────────────┐                                           │
         │     │ 6. Verificación (verify)  │ ──► (Condicional: si hay VerifierEngine)  │
         │     └─────────────┬─────────────┘                                           │
         │                   │                                                         │
         │            ¿Fallo detectado?                                                │
         │     ┌─────────────┴─────────────┐                                           │
         │[SÍ] ▼                           ▼ [NO]                                      │
         │ ┌───────────────────┐           │                                           │
         │ │  Compensación     │           │                                           │
         │ │    (rollback)     │           │                                           │
         │ └─────────┬─────────┘           │                                           │
         │           └─────────────┬───────┘                                           │
         │                         ▼                                                   │
         │     ┌───────────────────────────┐                                           │
         │     │ 7. Evaluación (evaluate)  │ ──► (Obligatorio: Verificación semántica) │
         │     └─────────────┬─────────────┘                                           │
         │                   │                                                         │
         │        ¿Objetivo alcanzado?                                                 │
         │        ├── Needs More Info & iter < 3 ──────────────────────────────────────┘
         │        └── Satisfecho / Fallo / iter >= 3
         │                   │
         │                   ▼
         │     ┌───────────────────────────┐
         │     │ 8. Conclusión (conclude)  │ ──► Generación de salida AgentOutput
         │     └─────────────┬─────────────┘
         │                   ▼
         └────────────────► [END]
```

### Ciclo Reflexivo y Guardarraíles de Iteración
- **`evaluate` $\rightarrow$ `reason`:** Si el evaluador determina que se requiere información adicional (`GoalStatus.NEEDS_MORE_INFO`), reinyecta el contexto en `reason` incrementando el contador `iteration`.
- **Límite determinista (`max_iterations = 3`):** Al alcanzar el umbral de iteraciones sin resolver la meta, el enrutador condicional aborta de forma segura hacia `conclude` evitando bucles infinitos y consumo descontrolado de tokens.

---

## 3. Contratos de Comunicación (I/O)

`jg_agente` implementa los contratos canónicos de `jg_agente_sdk`:

### `AgentInput` (Estímulo de Entrada)
```python
class AgentInput(BaseModel):
    execution_id: str                          # Identificador único de la ejecución
    thread_id: str                             # Identificador de sesión (alias: session_id)
    correlation_id: str | None = None          # Trazabilidad distribuida (X-Correlation-ID)
    prompt: str                                # Instrucción normalizada (alias: message)
    parameters: dict[str, Any] = {}            # Argumentos parametrizados
    user_context: UserContext | None = None    # Identidad y permisos RBAC del invocador
    metadata: dict[str, Any] = {}              # Metadatos complementarios
    callback_url: str | None = None            # Webhook para ejecuciones asíncronas
    created_at: datetime                       # Timestamp UTC de recepción
```

### `AgentOutput` (Respuesta Sintetizada)
```python
class AgentOutput(BaseModel):
    execution_id: str
    thread_id: str
    correlation_id: str | None = None
    status: ExecutionStatus                    # completed, waiting_approval, failed, cancelled
    response: str                              # Respuesta final o motivo de espera
    data: dict[str, Any] | None = None         # Artefactos y traza de pasos (cognitive_steps)
    execution_time_ms: float = 0.0             # Duración observada en ms
    requires_approval: bool = False            # Flag de suspensión HITL
    pending_approval_id: str | None = None     # Identificador de acción en espera
    error: str | None = None
    metadata: dict[str, Any] = {}
    completed_at: datetime
```

---

## 4. Protocolo Criptográfico Inter-Servicio (HMAC-SHA256)

`jg_agente` es un plano de ejecución **agnóstico y autónomo**. Cualquier cliente o invocador externo —ya sea una plataforma de mensajería (bots de **Telegram** o webhooks de **WhatsApp**), un orquestador, un API Gateway, un backend personalizado o una consola de control como **`jg_dashboard`**— puede interactuar con el agente enviando peticiones autenticadas mediante el contrato canónico HMAC-SHA256 validado por `verify_control_plane_auth` ([app/security/auth.py](app/security/auth.py)):

```text
canonical_string = f"{METHOD}\n{PATH}\n{TIMESTAMP}\n{SHA256(RAW_BODY)}"
signature = HMAC-SHA256(canonical_string, PERMANENT_AGENT_SECRET).hexdigest()
```

| Cabecera | Formato | Validación |
| :--- | :--- | :--- |
| **`X-Signature`** | Hexadecimal en minúsculas | Verificación en tiempo constante (`hmac.compare_digest`). |
| **`X-Timestamp`** | Epoch UNIX (segundos) | Ventana anti-replay estricta: $\|t_{\text{actual}} - t_{\text{req}}\| \le 300\text{ s}$. |
| **`X-Agent-ID`** | UUID / String | Coincidencia unívoca con el identificador del agente (`AGENT_ID`). |
| **`X-Correlation-ID`** | UUID v4 | Propagado en logs y trazas de auditoría (opcional pero recomendado). |

Cualquier ecosistema o pasarela externa que comparta el secreto criptográfico simétrico (`PERMANENT_AGENT_SECRET`) puede disparar ejecuciones (`POST /executions/trigger`) y gestionar resoluciones HITL (`POST /executions/{thread_id}/approve`) sin depender en absoluto de que exista una instancia de `jg_dashboard` en la red.

---

## 5. Modos de Funcionamiento, Arranque y Utilidad del Registro

### ¿Para qué sirve registrar los agentes en un Dashboard?
Aunque `jg_agente` puede operar de forma aislada, en infraestructuras productivas y multi-agente el registro en un panel de control resuelve necesidades operativas críticas:
1. **Inventario y Descubrimiento Dinámico de Capacidades:** El agente publica en tiempo real qué herramientas, plugins y modelos tiene activos sin requerir inspección manual de código.
2. **Gobernanza Human-In-The-Loop (HITL) Visual:** Proporciona una interfaz web interactiva para que operadores humanos auditen y aprueben/rechacen operaciones de riesgo `HIGH` o `CRITICAL` con control de concurrencia pesimista.
3. **Telemetría y Monitorización de Salud (Heartbeats):** Supervisa el estado de los agentes mediante pulsos periódicos cada 30 segundos, detectando caídas o sobrecargas en la red.
4. **Aprovisionamiento Zero-Trust con Bootstrap Tokens:** Evita el uso de contraseñas estáticas en archivos de configuración mediante tokens temporales de enrolamiento de un solo uso (TTL 24h).
5. **Auditoría Forense Centralizada:** Registra de forma inmutable quién solicitó cada acción, quién la autorizó y qué herramientas se accionaron.

> **Panel Oficial de la Comunidad:** Para dar respuesta a estas necesidades de gobernanza sin acoplar el runtime, hemos desarrollado y puesto a disposición de la comunidad el proyecto de código abierto **`jg_dashboard`**:  
> 👉 **Repositorio oficial en GitLab:** [https://gitlab.com/javiergalvez-ia/jg_dashboard](https://gitlab.com/javiergalvez-ia/jg_dashboard)  
> *Para una descripción en profundidad de los flujos de despliegue, consulta la guía [07. Modos de Funcionamiento, Topologías y Registro](docs/es/07_operational_modes.md).*

### ¿Es el registro en un Dashboard obligatorio o bloqueante?
**NO, por defecto NO es bloqueante (`REQUIRE_DASHBOARD_REGISTRATION=False`).**  
`jg_agente` está diseñado con máxima tolerancia a fallos para operar en entornos autónomos o desconectados. Durante la secuencia de arranque en [app/core/registration.py](app/core/registration.py), el agente resuelve su identidad y credenciales siguiendo un orden de prelación determinista:

```text
  [Inicio: Arranque de jg_agente]
                 │
                 ▼
  ¿PERMANENT_AGENT_SECRET y AGENT_ID en env?
         ├─── SÍ ───► Cargar credenciales de env ──► ¿VERIFY_CREDENTIALS_ON_BOOT?
         │                                                    ├─── NO ──► Arranque Autónomo
         │                                                    └─── SÍ ──► Sondear heartbeat
         └─── NO
                 │
                 ▼
  ¿Existe .agent_credentials.json?
         ├─── SÍ ───► Cargar credenciales locales POSIX 0600
         └─── NO
                 │
                 ▼
  ¿Existe AGENT_BOOTSTRAP_TOKEN?
         ├─── SÍ ───► POST /api/v1/agents/register ──► Persistir credenciales ──► Arranque
         └─── NO ───► Modo Local / Desconectado (jg_agente_local)
```

### Resumen de Modos de Operación:

1. **Modo 1: Standalone / Desacoplado (Telegram, WhatsApp, API Gateways, n8n):**
   - Configuración vía variables de entorno (`AGENT_ID`, `PERMANENT_AGENT_SECRET`).
   - El cliente externo firma directamente cada petición REST.
   - Si `DASHBOARD_URL` no está disponible, el agente emite un aviso en el log y continúa su arranque sin bloquearse.
   - Opcional: configurar `ENABLE_HEARTBEAT=False` y `VERIFY_CREDENTIALS_ON_BOOT=False` para aislar el tráfico saliente.

2. **Modo 2: Clúster Gestionado con Control Plane (`jg_dashboard`):**
   - Se enrola dinámicamente mediante `AGENT_BOOTSTRAP_TOKEN` emitido por el dashboard.
   - Guarda credenciales en `.agent_credentials.json` con permisos restrictivos `0600`.
   - Emite telemetría periódica cada 30 segundos y delega la interfaz HITL a la consola Filament.

3. **Modo 3: Modo Desconectado / Local (Desarrollo y CI/CD):**
   - Arranca como `jg_agente_local` sin claves obligatorias, con checkpointer en memoria (`CHECKPOINT_SAVER=memory`) y LLMs simulados (`LLM_PROVIDER=mock`).

4. **Modo 4: Edge Worker / Ejecución Asíncrona con Webhooks:**
   - Invocación con `sync=false`, delegando la respuesta inmediata (`202 Accepted`) y notificando el resultado al webhook configurado en `callback_url` con reintentos automáticos.

---

## 6. Persistencia y Checkpointing

El almacenamiento persistente se organiza sobre PostgreSQL mediante `DualPostgresSaver` ([app/core/checkpointer.py](app/core/checkpointer.py)):

1. **Vistas Canónicas de Checkpoints:**  
   Se crean y mantienen automáticamente las vistas sobre las tablas nativas de LangGraph:
   - `core_checkpoints` $\rightarrow$ `checkpoints`
   - `core_checkpoint_blobs` $\rightarrow$ `checkpoint_blobs`
   - `core_checkpoint_writes` $\rightarrow$ `checkpoint_writes`
2. **Tablas Relacionales de Dominio:**
   - **`core_executions`:** Ciclo de vida, parámetros, respuestas y latencias de cada ejecución.
   - **`core_audit_records`:** Trazabilidad inmutable de decisiones tomadas por `SecurityGuard` y ejecuciones de herramientas.
3. **Resiliencia y Modo Degradado:**
   - Si PostgreSQL no responde tras agotar los reintentos (`CHECKPOINT_MAX_RETRIES=3`), conmuta automáticamente a `MemorySaver` en modo degradado y vuelca las ejecuciones críticas en disco local (`data/emergency_executions/{execution_id}.json`).

---

## 7. Variables de Entorno y Configuración

| Variable | Descripción | Valor por Defecto |
| :--- | :--- | :--- |
| `ENV` | Entorno de ejecución (`development`, `production`). | `development` |
| `AGENT_ID` | Identificador único del agente en el ecosistema. | `jg_agente_local` |
| `AGENT_PORT` | Puerto interno del servidor Uvicorn. | `8000` |
| `UVICORN_WORKERS` | Número de workers paralelos asíncronos. | `2` |
| `PERMANENT_AGENT_SECRET` | Secreto simétrico para firma HMAC con clientes externos (Telegram, Dashboard, etc.). | Requerido en producción |
| `AGENT_BOOTSTRAP_TOKEN` | Token temporal de 24h para registro dinámico Zero-Trust (opcional). | `None` |
| `REQUIRE_DASHBOARD_REGISTRATION` | Si es `true`, exige registro exitoso obligatorio en boot para continuar. | `false` (No bloqueante) |
| `VERIFY_CREDENTIALS_ON_BOOT` | Comprueba credenciales contra el endpoint de heartbeat al iniciar. | `true` (Fallo de red no bloquea) |
| `DASHBOARD_URL` | URL base de red privada para telemetría/registro (si existe Control Plane). | `http://jg_dashboard:8080` |
| `ENABLE_HEARTBEAT` | Emisión periódica de telemetría hacia el Dashboard (desactivable en standalone). | `true` (intervalo 30s) |
| `DATABASE_URL` | Cadena de conexión asyncpg a PostgreSQL. | `postgresql+asyncpg://...` |
| `CHECKPOINT_SAVER` | Backend de checkpoints (`postgres` o `memory`). | `postgres` |
| `LLM_PROVIDER` | Proveedor cognitivo (`groq`, `openai`, `gemini`, `mock`). | `groq` |
| `LLM_MODEL` | Identificador del modelo fundacional. | `llama-3.3-70b-versatile` |
| `PLUGINS_DIR` | Carpeta para escaneo de plugins locales. | `plugins` |
| `ENABLED_PLUGINS` | Lista separada por comas de plugins activos (vacío = todos). | Vacío |
| `REQUIRED_PLUGINS` | Lista separada por comas de plugins obligatorios para el boot (Fail-Fast). | Vacío |
| `REQUIRED_TOOLS` | Lista separada por comas de herramientas obligatorias para el boot (Fail-Fast). | Vacío |
| `REQUIRE_PLANNER` | Si es `true`, exige un motor de planificación registrado en el boot. | `false` |
| `REQUIRE_OBSERVER` | Si es `true`, exige un motor de observación registrado en el boot. | `false` |
| `REQUIRE_VERIFIER` | Si es `true`, exige un motor de verificación registrado en el boot. | `false` |
| `SSRF_ENFORCE_PROTECTION`| Bloqueo estricto de redes privadas y metadatos cloud. | `true` |
| `EMERGENCY_PERSISTENCE_DIR` | Directorio local de spooling ante caídas irrecuperables de PostgreSQL. | `data/emergency_executions` |
| `AUDIT_LOG_MAX_HISTORY` | Capacidad del búfer circular en memoria para trazas de auditoría. | `1000` |
| `EXECUTION_CALLBACK_TIMEOUT_SECONDS` | Timeout de llamadas webhook HTTP para notificaciones asíncronas. | `5.0` |
| `EXECUTION_CALLBACK_MAX_RETRIES` | Reintentos máximos para entrega de webhooks asíncronos. | `3` |

---

## 8. Despliegue Multi-Agente (Docker Compose)

`jg_agente` utiliza una **única imagen de contenedor universal**. La especialización funcional se logra mediante la activación de plugins y variables de entorno:

```yaml
services:
  # Agente de Diálogo y Asistencia
  jg_agente_conversacional:
    image: registry.cabocom.net/javiergalvez-ia/jg_agente:latest
    environment:
      AGENT_ID: "a0000000-0000-0000-0000-000000000001"
      AGENT_NAME: "Agente Conversacional"
      ENABLED_PLUGINS: "jg_plugin_conversational"
      DATABASE_URL: "postgresql+asyncpg://postgres:${DB_PASS}@jg_agente_postgres:5432/jg_agente_conversacional"
      PERMANENT_AGENT_SECRET: "${JG_CONVERSATIONAL_SECRET}"
      AZURE_MAPS_KEY: "${AZURE_MAPS_KEY}"
    ports:
      - "127.0.0.1:8001:8000"

  # Agente SRE / DevOps de Infraestructura (con HITL)
  jg_agente_devops:
    image: registry.cabocom.net/javiergalvez-ia/jg_agente:latest
    environment:
      AGENT_ID: "a0000000-0000-0000-0000-000000000002"
      AGENT_NAME: "Agente DevOps"
      ENABLED_PLUGINS: "jg_plugin_devops"
      DATABASE_URL: "postgresql+asyncpg://postgres:${DB_PASS}@jg_agente_postgres:5432/jg_agente_devops"
      PERMANENT_AGENT_SECRET: "${JG_DEVOPS_SECRET}"
      DOCKER_HOST: "tcp://jg_docker_socket_proxy:2375"
    ports:
      - "127.0.0.1:8002:8000"
```

---

## 9. Verificación de Calidad y Pruebas

El runtime cuenta con una suite integral automatizada de **441 pruebas** (unitarias, integración de grafos, contratos drift y validación de seguridad):

```bash
# Verificación integral automatizada (Linter, Typecheck y Tests)
./scripts/check.sh

# Ejecución directa con pytest
pytest tests/
```

---

## 10. Política de Licenciamiento

Este proyecto está disponible bajo un modelo de Doble Licenciamiento (Dual Licensing):

1. **Código Abierto (GNU AGPL-3.0):** Libre para evaluación, desarrollo personal y proyectos comunitarios bajo la [GNU Affero General Public License v3.0](LICENSE). Si interactúas con este software o derivados a través de una red, debes mantener y compartir el código fuente bajo los mismos términos.
2. **Licencia Comercial Enterprise:** Diseñada para organizaciones que requieren desplegar `jg_agente` en entornos propietarios, integrarlo con soluciones cerradas o que no pueden asumir los requisitos copyleft de red de la AGPL-3.0.

Para consultas sobre licencias comerciales: visita [https://javiergalvez.com](https://javiergalvez.com).
