# CONTEXTO DE PROYECTO: jg_agente

**Versión del documento:** 2.25.0  
**Fecha de consolidación:** 5 de septiembre de 2026  
**Componente:** Execution Plane (Motor Autónomo de Ejecución)  
**Estado:** Fases 01 a 08 completadas (100%). Fase 08 completada íntegramente: ISSUE-F08-T01, ISSUE-F08-T02 e ISSUE-F08-T03 (Cliente de registro Zero-Trust con bootstrap token, persistencia y recarga de credencial permanente con permisos POSIX 0600, verificación activa en boot con tolerancia a fallos e invalidación segura ante 401, y bucle de heartbeat periódico con telemetría de salud, memoria portable, uptime y ciclo de vida en lifespan).

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
   Toda invocación a herramientas pasa por el `SecurityGuard` del Core, que verifica permisos, niveles de riesgo (`RiskLevel`), idempotencia, directivas SSRF y políticas HITL antes de la ejecución.

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
   - `conclude`: Síntesis de la respuesta final y emisión de `AgentOutput`.

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
- `POST /executions/trigger`: Inicia una ejecución síncrona o asíncrona.
- `GET /executions/{thread_id}`: Consulta estado actual, checkpoints e historial.
- `POST /executions/{thread_id}/approve`: Reanuda un flujo pausado por HITL.
- `POST /executions/{thread_id}/reject`: Cancela un flujo pausado por HITL.
- `GET /capabilities`: Devuelve catálogo de tools, engines y versiones cargadas.
- `GET /health` y `GET /metrics`: Telemetría y estado de salud.

---

## 8. Criterios de Éxito del MVP

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
