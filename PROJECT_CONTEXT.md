# CONTEXTO DE PROYECTO: jg_agente

**Versión del documento:** 2.39.1  
**Fecha de consolidación:** 9 de noviembre de 2026  
**Componente:** Execution Plane (Motor Autónomo de Ejecución)  
**Estado:** Fases 01 a 11 completadas (100%). Integración con `jg_agente_sdk` consolidada y sincronización automática de *mirror* público hacia `https://github.com/cabocom/jg_agente` vía GitLab CI/CD (`workspace#8`).  
- Soporte i18n y Externalización de Prompts (jg_agente#80): Desacoplamiento y externalización de plantillas de prompts de `reason.py` hacia `app/prompts/templates/{es,en,fr,de,it}/` gestionadas por `PromptManager`. Soporte multilingüe en 5 idiomas (Español, Inglés, Francés, Alemán, Italiano), resolución jerárquica de locales (`request.locale -> plugin.default_locale -> settings.DEFAULT_LOCALE -> 'es'`), directivas cognitivas localizadas y trazabilidad de idioma en `CognitiveStepRecord`.
- Integración Canónica con `jg_agente_sdk` (REFACTOR-SDK-001): Establecimiento del SDK como Fuente Única de Verdad (SSOT) para contratos de herramientas (`AgentTool`, `ToolResult`, `RiskLevel`, `ToolType`) y plugins (`BasePlugin`, `BaseEngine`). `app.models.tools.AgentTool` hereda directamente de `jg_sdk.contracts.AgentTool` añadiendo únicamente el adaptador de LangChain (`as_langchain_tool`). Eliminada la duplicidad de 240 líneas de código.
- Razonamiento Iterativo Proactivo y Gobernanza HITL Multi-Paso:
  * Soporte de re-evaluación semántica en grafo cognitivo con `GoalStatus` (`satisfied`, `needs_more_info`), contador de iteraciones `iteration`/`max_iterations`, y deduplicación semántica (`_normalize_args`) que ignora metadatos artificiales (`request_id`) para evitar bucles ciegos sobre el mismo comando.
  * Planificación y Desglose HITL Transparente (`_expand_full_action_plan_with_llm`): En solicitudes operativas mutativas, el LLM formula de antemano el plan completo de etapas con metadatos de riesgo y acción, impidiendo ocultar mutaciones posteriores tras una primera aprobación.
  * Ejecución Multi-Paso Pre-Aprobada: En `execute_node`, el bypass de HITL autoriza todos los `step_id` del plan validado por el operador.
  * Trazabilidad Saga LIFO Detallada (`rollback_node`): Emite un `CognitiveStepRecord` por cada acción compensatoria ejecutada en orden inverso, permitiendo auditoría granular en el Dashboard.
- Fase 08 completada: Cliente de registro Zero-Trust, bootstrap tokens, CredentialStore (permisos POSIX 0600) y heartbeat periódico.  
- Fase 11 completada: Extracción e integración de plugins especializados (`jg_plugin_conversational`, `jg_plugin_devops` y `jg_plugin_datosgob`).  
- Despliegue Multi-Agente Unificado: Soporte de múltiples perfiles desde la misma imagen Docker mediante `ENABLED_PLUGINS` (`jg_agente_conversacional` en :8001, `jg_agente_devops` en :8002 y `jg_agente_datosgob` en :8881).  
- Persistencia Core y Aislamiento Multi-Agente (GLOBAL-002 / ISSUE-AGENT-003): Cada runtime dispone de su propia base de datos dedicada en el PostgreSQL compartido `jg_agente_postgres` (puerto 5433), garantizando aislamiento absoluto de checkpoints, transacciones e hilos de ejecución sin alterar el agnosticismo del Core.  
- Post-Auditoría Codex (GLOBAL-001 / ISSUE-AGENT-001): Autenticación estricta y anti-replay en router `/executions` con firma canónica HMAC-SHA256 (`METHOD\nPATH\nTIMESTAMP\nSHA256(BODY)`), ventana de 300s y validación de `X-Agent-ID`.  
- Post-Auditoría 2 (GLOBAL-01 / GitLab jg_agente#52): Erradicación total de secretos pre-aprovisionados hardcodeados en orquestación (`docker-compose.yml`); adopción de interpolación obligatoria `${JG_CONVERSATIONAL_SECRET:?err}` y `${JG_DEVOPS_SECRET:?err}` garantizando sincronización simétrica de firmas HMAC con el Dashboard.  
- Post-Auditoría 2 (GLOBAL-02 / GitLab jg_agente#53): Consolidación del flujo criptográfico simétrico para registro dinámico de agentes; jg_agente persiste localmente el `permanent_secret` suministrado por el Dashboard en `.agent_credentials.json` (permisos 0600) y valida las peticiones entrantes contra su secreto único mientras el Dashboard lo preserva cifrado en reposo para computar las cabeceras `X-Signature`.  
- Post-Auditoría 2 (GLOBAL-03 / GitLab jg_agente#54): Compatibilización de tiempos de respuesta del ciclo cognitivo de 9-10 nodos (`observe` a `conclude`); elevación del timeout de conexión síncrona en el Dashboard a 120s (`AGENT_HTTP_TIMEOUT=120`) y consolidación del flujo asíncrono (`sync=false` / `parameters.async=True`) con respuesta inmediata HTTP 202 Accepted encolada en BackgroundTasks y consulta periódica vía `GET /executions/{thread_id}`.  
- Post-Auditoría 2 (GLOBAL-05 / GitLab jg_agente#56): Trazabilidad distribuida y propagación de Correlation-ID; implementación de `app/core/correlation.py` con `ContextVar`, `CorrelationLogFilter` y `CorrelationIdMiddleware` para captura/retorno de `X-Correlation-ID`; inyección en esquemas Pydantic (`AgentInput`, `AgentOutput`, `ExecutionThreadDetail`, `AuditRecord`, `AgentState`), en la orquestación de LangGraph y en el registro persistido de `SecurityAuditLogger` (`CoreAuditRecord.details`).  
- Post-Auditoría 2 (AGENTE-SEC-01 / GitLab jg_agente#57): Mitigación de escape de contenedor y compromiso root; erradicación de montaje directo de `/var/run/docker.sock` y eliminación de `user: "0:0"` en `jg_agente_devops` (ejecución no-root obligatoria UID 10001 `appuser`); integración del servicio `jg_docker_socket_proxy` (`tecnativa/docker-socket-proxy`) con ACLs restrictivas (`CONTAINERS=1`, `POST=1`, `VOLUMES=0`, `EXEC=0`), vinculación de puertos a `127.0.0.1` y protección en código (`PROTECTED_INFRASTRUCTURE_CONTAINERS`).  
- Invocación Síncrona en Adaptador LLM: `OpenAICompatibleChatModel` implementa `_generate()` delegando de forma segura en `_agenerate()` (mediante aislamiento en ThreadPoolExecutor en presencia de event loops activos), permitiendo la interoperabilidad transparente con herramientas y plugins que ejecutan invocaciones síncronas (`llm.invoke()`).
- Suite de Pruebas: Suite completa pasando al 100% (Ruff, MyPy estricto en 112 ficheros, 371+ tests Pytest).

---

## 1. Propósito del Proyecto

`jg_agente` es el **Execution Plane** (motor autónomo de ejecución desacoplado) del ecosistema. Su propósito exclusivo es ejecutar tareas de razonamiento, planificación y acción orientadas a objetivos mediante grafos de estados (LangGraph), operando como un proceso aislado dentro de una red privada.

`jg_agente` no está expuesto directamente a Internet ni interactúa directamente con usuarios finales. Recibe estímulos normalizados desde el plano de control (`jg_dashboard`) o adaptadores externos autorizados, ejecuta el ciclo cognitivo necesario mediante herramientas (`AgentTool`) y motores de dominio (`Engines`), y devuelve resultados normalizados.

---

## 2. Principios Arquitectónicos Fundamentales

1. **Agnosticismo Radical del Core:**
   El Core de `jg_agente` no contiene conocimiento de dominios específicos (telefonía, devops, finanzas, etc.). Queda terminantemente prohibido el uso de bifurcaciones condicionales basadas en el tipo de agente:
   ```python
   # PROHIBIDO EN EL CORE:
   if agent_type == "conversational":
       ...
   if is_devops:
       ...
   ```
   El comportamiento se define exclusivamente a través de la composición de capacidades (`CapabilityRegistry`) aportadas por los plugins instalados.

2. **Ausencia Absoluta de Interfaces Externas en el Agente:**
   `jg_agente` **NO contiene interfaces de comunicación**. No conoce Asterisk, Telegram, WhatsApp, Slack, Webhooks de terceros ni formatos propietarios.
   - Toda entrada al agente es un `AgentInput` normalizado.
   - Toda salida del agente es un `AgentOutput` normalizado.
   - Todos los protocolos y adaptadores de transporte pertenecen a `jg_dashboard` o a gateways externos.

3. **Separación Estricta de Planos:**
   - **Control Plane (`jg_dashboard`):** Usuarios, RBAC, registro de agentes, emisión de tokens, monitoreo agregado, consola HITL, adaptadores externos.
   - **Execution Plane (`jg_agente`):** Grafo LangGraph, plugins, engines, tools, sandbox de ejecución, persistencia local de ejecuciones y checkpoints.
   - **Regla de oro de persistencia:** `jg_dashboard` **NUNCA** se conecta a la base de datos de `jg_agente`. Toda interacción es vía API REST autenticada (`POST /executions/trigger`, `POST /executions/{id}/approve`, etc.).

4. **Inversión de Control mediante Plugins:**
   Un Plugin es la unidad mínima de extensión distribuible. Los plugins declaran herramientas (`AgentTool`), modelos y engines especializados. El Core orquesta; el plugin provee capacidades.

5. **Seguridad por Diseño (Security First):**
   Toda invocación a herramientas pasa por el `SecurityGuard` del Core, que verifica permisos, niveles de riesgo (`RiskLevel`), sanitización universal recursiva contra inyección de comandos shell y directory traversal (independiente de la clave o profundidad de anidación), directivas SSRF y políticas HITL antes de la ejecución.

---

## 3. Matriz de Responsabilidades

| Responsabilidad | Core (`jg_agente`) | Plugins (`jg_plugin_*`) | Dashboard (`jg_dashboard`) |
| :--- | :--- | :--- | :--- |
| **Orquestación del Grafo** | **Exclusiva** (LangGraph) | Prohibida | Invocación remota vía API |
| **Modelos de Entrada/Salida** | Define `AgentInput`/`AgentOutput` | Consume contratos | Normaliza entradas externas |
| **Herramientas de Negocio** | Provee contrato `AgentTool` | **Implementa Tools** | Solo visualiza metadata |
| **Engines de Dominio** | Define interfaces abstractas | Implementa engines concretos | Ninguna |
| **Evaluación de Riesgo** | `SecurityGuard` (Políticas) | Declara metadata de riesgo | Visualiza y aprueba (HITL) |
| **Rollback de Operaciones** | Ejecuta compensaciones | Declara `rollback_func` | Ninguna |
| **Persistencia de Checkpoints** | Tablas `core_*` | Tablas prefijadas `plugin_*` | Tablas propias (DB separada) |
| **Gestión de Identidad/Usuarios** | Ninguna (solo API keys internas) | Ninguna | **Exclusiva** (JWT, RBAC) |
| **Adaptadores (Asterisk, Telegram)** | **Prohibido** | Prohibido | **Exclusiva** |

---

## 4. Contratos Principales del Core

### 4.1 `AgentInput` y `AgentOutput`

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


class AgentInput(BaseModel):
    execution_id: str = Field(..., description="ID único de la ejecución asignado por el invocador")
    thread_id: str = Field(..., description="ID de sesión o hilo conversacional persistente")
    prompt: str = Field(..., description="Estímulo principal de texto normalizado")
    parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Parámetros opcionales del contexto"
    )
    user_context: Optional[Dict[str, Any]] = Field(
        default=None, description="Contexto del usuario autenticado en el Dashboard"
    )
    locale: str = Field(
        default="es", description="Código ISO 639-1 del idioma de interacción ('es', 'en', 'fr', 'de', 'it')"
    )


class AgentOutput(BaseModel):
    execution_id: str
    thread_id: str
    status: str  # "completed", "waiting_approval", "failed", "cancelled"
    response: str
    data: Optional[Dict[str, Any]] = None
    execution_time_ms: float
    requires_approval: bool = False
    pending_approval_id: Optional[str] = None
```

### 4.2 `AgentTool` y `ToolResult`

Toda herramienta en el sistema debe satisfacer el contrato estricto `AgentTool`:

```python
from enum import Enum
from typing import Callable, Optional, Type, Dict, Any
from pydantic import BaseModel


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolType(str, Enum):
    READ = "read"
    MUTATION = "mutation"
    INTERACTION = "interaction"


class ToolResult(BaseModel):
    success: bool
    output: Any
    error: Optional[str] = None
    duration_ms: float
    metadata: Dict[str, Any] = {}
    rollback_context: Optional[Dict[str, Any]] = None


class AgentTool(BaseModel):
    name: str
    description: str
    category: str
    version: str = "1.0.0"
    args_schema: Type[BaseModel]
    func: Callable[..., ToolResult]
    risk_level: RiskLevel = RiskLevel.LOW
    required_permissions: List[str] = []
    tool_type: ToolType = ToolType.READ
    read_only: bool = True
    reversible: bool = False
    idempotent: bool = False
    makes_http_requests: bool = False
    timeout_sec: float = 30.0
    rollback_func: Optional[Callable[[Dict[str, Any]], ToolResult]] = None
```

### 4.3 Semántica de Rollback
- Si `reversible == True`, la herramienta DEBE proporcionar obligatoriamente un `rollback_func` válido.
- La ejecución de una herramienta reversible genera un `rollback_context` dentro de su `ToolResult`.
- Si `reversible == False`, cualquier intento de compensación registrará explícitamente `NO_ROLLBACK_AVAILABLE`.
- El planificador o el motor de recuperación jamás contiene condicionales por nombre de herramienta (`if tool_name == ...`). Invoca directamente `tool.rollback_func(rollback_context)`.

---

## 5. Ciclo Cognitivo y Construcción del Grafo

### 5.1 Ciclo Teórico Completo
```text
ESTÍMULO (AgentInput)
   ↓
OBSERVAR (observe)
   ↓
RAZONAR (reason)
   ↓
DECIDIR / PLANIFICAR (plan)
   ↓
EVALUAR RIESGO (risk_assess)
   ↓
APROBACIÓN HUMANA (human_approval - HITL)
   ↓
ACTUAR (execute)
   ↓
VERIFICAR (verify)
   ↓
DIAGNOSTICAR / ROLLBACK (diagnose / rollback)
   ↓
CONCLUIR (conclude)
   ↓
SALIDA (AgentOutput)
```

### 5.2 Ensamblado del Grafo en Tiempo de Boot
El grafo **NO se ensambla dinámicamente en cada ejecución**, sino una única vez durante el inicio de la aplicación en función de las capacidades registradas:

1. **Nodos Base Obligatorios:**
   - `reason`: Análisis del estímulo y toma de decisiones mediante LLM.
   - `execute`: Invocación controlada de herramientas con paso previo por `SecurityGuard`.
   - `evaluate`: Evaluación semántica del objetivo (`satisfied`, `needs_more_info`, `blocked_missing_capability`, `failed`) con síntesis directa al usuario en `explanation` (sin meta-comentarios de auditoría en tercera persona).
   - `conclude`: Síntesis de la respuesta final y emisión de `AgentOutput` (con filtrado defensivo anti-metacomentarios priorizando datos limpios de las herramientas).

2. **Nodos Opcionales Condicionados por Capacidades:**
   - Si `CapabilityRegistry` tiene un `ObserverEngine` registrado → se intercala el nodo `observe` antes de `reason`.
   - Si `CapabilityRegistry` tiene un `PlannerEngine` registrado → se intercala el nodo `plan` tras `reason`.
   - Si se planifican acciones con `RiskLevel >= HIGH` → el Core enlaza automáticamente `risk_assess` y `human_approval`.
   - Si `CapabilityRegistry` tiene un `VerifierEngine` registrado → se enlaza el nodo `verify` tras `execute`.
   - Si un paso falla y la herramienta es reversible → se activa el nodo `rollback`.

### 5.3 Regla de Resolución de Conflictos en Plugins
- En la versión 1.0 (MVP), los engines de ciclo (`ObserverEngine`, `PlannerEngine`, `VerifierEngine`, `DiagnosticEngine`) son **capacidades exclusivas**.
- Puede haber múltiples plugins activos aportando herramientas simultáneamente (ej: `WeatherTool` de plugin conversacional y `DockerRestartTool` de plugin devops).
- Sin embargo, si dos plugins intentan registrar la misma capacidad exclusiva (por ejemplo, dos `PlannerEngine` distintos), el `CapabilityRegistry` abortará inmediatamente el arranque con un error explícito:
  ```text
  BootConflictError: Engine conflict detected for capability 'planner_engine'.
  Registered by 'plugin_devops_v1', attempted by 'plugin_custom_planner'.
  Aborting startup.
  ```
  **Queda terminantemente prohibida la sobrescritura silenciosa ("último registrado gana").**

---

## 6. Persistencia de Datos

Para el MVP se utiliza **una única instancia y base de datos PostgreSQL** para `jg_agente`:
- **Esquema del Core:** Tablas gestionadas por Alembic con prefijo `core_`:
  - `core_executions`: Registro de ejecuciones, tiempos y estados.
  - `core_checkpoints`: Checkpoints de LangGraph (utilizando `PostgresSaver`).
  - `core_audit_records`: Registros del `SecurityAuditLogger`.
- **Esquema de Plugins:** Tablas gestionadas por cada plugin con prefijo obligatorio de dominio:
  - Ejemplo DevOps: `devops_infra_snapshots`, `devops_circuit_breakers`.
  - Ningún plugin puede modificar ni depender directamente de columnas o tablas `core_*`.
- **Checkpointing de `AgentState`:** El campo `environment_snapshot` en `AgentState` se almacena como `Optional[Dict[str, Any]]` en la base de datos para garantizar resiliencia en la serialización/deserialización JSON de LangGraph. Los plugins aportan helpers para hidratar modelos tipados de Pydantic dentro de sus propios nodos.

---

## 7. Protocolo de Registro y Comunicación con `jg_dashboard`

El ciclo de confianza y aprovisionamiento entre `jg_agente` y `jg_dashboard` sigue un flujo estricto:

```text
[Administrador]
      │ 1. Crea agente en Dashboard UI (introduce nombre)
      ▼
[jg_dashboard]
      │ 2. Genera: agent_id (UUID) + bootstrap_token (TTL 24h, 1 solo uso)
      ▼
[Desarrollador / Ops]
      │ 3. Arranca jg_agente inyectando AGENT_BOOTSTRAP_TOKEN y DASHBOARD_URL
      ▼
[jg_agente (Boot)]
      │ 4. POST /agents/register con bootstrap_token
      ▼
[jg_dashboard]
      │ 5. Valida token, marca consumido, emite permanent_agent_secret
      ▼
[jg_agente]
      │ 6. Almacena permanent_agent_secret en disco/entorno local seguro
      │ 7. Inicia ciclo recurrente de heartbeat (POST /agents/heartbeat)
      ▼
[Reinicios Posteriores]
      │ 8. Arranca directamente autenticándose con permanent_agent_secret (sin bootstrap_token)
```

### Endpoints del Agente (API Interna)
- `POST /executions/trigger`: Inicia una ejecución síncrona o asíncrona *(Requiere HMAC `X-Signature`, `X-Timestamp`, `X-Agent-ID`)*.
- `GET /executions/{thread_id}`: Consulta estado actual, checkpoints e historial *(Requiere HMAC `X-Signature`, `X-Timestamp`, `X-Agent-ID`)*.
- `POST /executions/{thread_id}/approve`: Reanuda un flujo pausado por HITL *(Requiere HMAC `X-Signature`, `X-Timestamp`, `X-Agent-ID`)*.
- `POST /executions/{thread_id}/reject`: Cancela un flujo pausado por HITL *(Requiere HMAC `X-Signature`, `X-Timestamp`, `X-Agent-ID`)*.
- `GET /capabilities`: Devuelve catálogo de tools, engines y versiones cargadas.
- `GET /health` y `GET /metrics`: Telemetría y estado de salud.

> [!NOTE]
> **Contrato Canónico de Autenticación (`/executions/*`):**
> `canonical_string = METHOD\nPATH\nTIMESTAMP\nSHA256(RAW_BODY)`  
> La firma HMAC-SHA256 se valida con ventana anti-replay de $\pm 300$ segundos contra el secreto permanente del agente. Cualquier discrepancia responde con HTTP 401 Unauthorized.

---

## 8. Subsistema de Internacionalización y Prompts (i18n)

A partir de la versión 2.39.0 (`jg_agente#80`), el nodo cognitivo `reason` y los subsistemas de prompt engineering están completamente desacoplados y localizados:

- **Catálogo de Plantillas (`app/prompts/templates/<locale>/`):**
  - Idiomas soportados: Español (`es`), Inglés (`en`), Francés (`fr`), Alemán (`de`), Italiano (`it`).
  - Plantillas externalizadas en texto plano:
    * `system.txt`: Instrucción canónica del rol y directivas de comportamiento.
    * `hitl_planning.txt`: Desglose estructurado de planes de acción multi-etapa para aprobación HITL.
    * `hitl_human.txt`: Directiva del operador humano con advertencias de riesgo.
    * `intent_classifier.txt`: Clasificación de intenciones y saludos/despedidas triviales.
    * `guidance.txt`: Realimentación cognitiva ante iteraciones sucesivas (`needs_more_info`).

- **Gestor Centralizado (`PromptManager` en `app/prompts/manager.py`):**
  - Jerarquía estricta de resolución de locale:
    ```text
    1. request.locale (parámetro de entrada AgentInput)
           ↓ (si es None o vacío)
    2. plugin.default_locale (metadato del plugin activo)
           ↓ (si es None o vacío)
    3. settings.DEFAULT_LOCALE (variable de entorno DEFAULT_LOCALE)
           ↓ (si es None o vacío)
    4. "es" (fallback canónico de seguridad)
    ```
  - Caching LRU en memoria para lectura ultrarrápida de plantillas sin penalización de I/O en runtime.
  - Directivas de concisión y longitud de respuesta adaptadas a cada idioma.
  - Detección de verbos imperativos mutativos y palabras clave de saludo en los 5 idiomas.
  - Metadatos de auditoría `CognitiveStepRecord` (`title`, `action`, `details={"locale": ...}`) completamente localizados.

---

## 9. Criterios de Éxito del MVP

El desarrollo de `jg_agente` se considerará validado únicamente cuando los dos siguientes casos de uso se ejecuten sobre el mismo Core sin ninguna modificación al código base:

1. **Caso A (Agente Conversacional Puro):**
   - Entrada normalizada (`AgentInput`).
   - Flujo de Grafo: `reason` → `execute` (invoca `WeatherTool`) → `conclude`.
   - Salida normalizada (`AgentOutput`).
   - Sin estado de infraestructura ni evaluación de riesgo HITL.

2. **Caso B (Agente DevOps Autónomo):**
   - Entrada normalizada (`AgentInput`: e.g. "Reiniciar contenedor web caído").
   - Flujo de Grafo: `observe` → `reason` → `plan` → `risk_assess` → `human_approval` (interrupción por riesgo HIGH) → aprobación vía Dashboard → `execute` (`DockerRestartTool`) → `verify` → `conclude`.
   - Manejo de Rollback automático en caso de fallo de verificación.

---

## 9. Decisiones Explícitamente Pospuestas (Fuera de Alcance MVP)

Las siguientes funcionalidades no forman parte del MVP y no deben incluirse en el backlog inicial:
- Memoria conversacional multi-turn avanzada persistente entre distintos canales.
- Mocks y adaptadores de telefonía Asterisk / SIP.
- Orquestación multi-agente, jerarquías y delegación de tareas (`AgentProxy`).
- Streaming por WebSockets o Server-Sent Events (SSE).
- Composición de múltiples `PlannerEngines` o pipelines de engines en paralelo.
- Firma criptográfica y verificación de integridad de paquetes de plugins.
- Autenticación mTLS entre Dashboard y Agentes.
- Soporte multitenant dinámico en una sola instancia de agente.
- Despliegue en clusters de Kubernetes y escalado horizontal automático.
