# jg_agente

**Motor Autónomo de Ejecución Cognitiva y Accionamiento**  
*Execution Plane del ecosistema jG*

---

## 1. ¿Qué es `jg_agente`?

`jg_agente` es un runtime de agentes autónomos basado en grafos de estados ([LangGraph](https://github.com/langchain-ai/langgraph)) diseñado para ejecutar tareas de razonamiento, planificación, invocación de herramientas seguras y verificación.

Opera como un **Execution Plane** aislado dentro de una red privada (sin exposición directa a Internet). No conoce protocolos de comunicación externos (Asterisk, Telegram, Slack, etc.); consume exclusivamente entradas normalizadas (`AgentInput`) y genera salidas estructuradas (`AgentOutput`).

---

## 2. ¿Qué problema resuelve?

1. **Fin del acoplamiento monolítico:** En sistemas anteriores (`jg-ai-gateway` y `Devops60k`), la lógica conversacional, la telefonía, la orquestación DevOps y las herramientas estaban entrelazadas con el ciclo de vida del agente. `jg_agente` proporciona un Core estrictamente agnóstico.
2. **Eliminación del código condicional por tipo de agente:** Elimina por completo estructuras como `if conversational:` o `if devops:`. El grafo de ejecución se configura de manera determinista al arrancar el proceso según las capacidades declaradas por los plugins cargados.
3. **Seguridad y reversibilidad garantizada:** Toda acción con efectos secundarios es auditada, categorizada por nivel de riesgo (`RiskLevel`), protegida contra SSRF y dotada de contratos formales de compensación (`rollback_func`).
4. **Gobernanza Human-In-The-Loop (HITL):** Los planes que implican mutaciones críticas se pausan de forma transparente en la base de datos de checkpoints y esperan autorización remota desde `jg_dashboard`.

---

## 3. Arquitectura General

```text
       ┌────────────────────────────────────────────────────────┐
       │                 jg_dashboard (Control Plane)           │
       │       Usuarios · RBAC · HITL Approval · Adaptadores    │
       └───────────────────────────┬────────────────────────────┘
                                   │ HTTP (API Interna / Red Privada)
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        jg_agente (Execution Plane)                     │
│                                                                        │
│  ┌───────────────────────┐         ┌────────────────────────────────┐  │
│  │   FastAPI Internal    │         │       CapabilityRegistry       │  │
│  │  /executions/trigger  │         │  (Tools, Engines, Validations) │  │
│  └───────────┬───────────┘         └───────────────▲────────────────┘  │
│              │                                     │ registra          │
│              ▼                                     │                   │
│  ┌───────────────────────┐         ┌───────────────┴────────────────┐  │
│  │    LangGraph Engine   │         │            Plugins             │  │
│  │   (observe -> reason  │         │  - jg_plugin_conversational    │  │
│  │    -> plan -> execute)│         │  - jg_plugin_devops            │  │
│  └───────────┬───────────┘         └────────────────────────────────┘  │
│              │                                                         │
│              ▼                                                         │
│  ┌───────────────────────┐         ┌────────────────────────────────┐  │
│  │     SecurityGuard     │◄───────►│      PostgreSQL Database       │  │
│  │ (SSRF, Risk, HITL)    │         │  (core_checkpoints, core_*)    │  │
│  └───────────────────────┘         └────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Flujo de Ejecución

El ciclo cognitivo se construye durante el boot del agente:

```text
[Estímulo: AgentInput]
         │
         ▼
     [observe] ──────────► (Opcional: Si existe ObserverEngine en plugins)
         │
         ▼
      [reason] ──────────► (Obligatorio: Razonamiento LLM base)
         │
         ▼
       [plan]  ──────────► (Opcional: Si existe PlannerEngine en plugins)
         │
         ▼
   [risk_assess] ────────► (Opcional: Si el plan contiene mutaciones)
         │
         ├─── [¿Riesgo >= HIGH?] ───► [human_approval] ──► (Pausa en Checkpoint)
         │                                                        │ (Aprobación en Dashboard)
         ▼                                                        ▼
     [execute] ──────────► (Obligatorio: Ejecución protegida por SecurityGuard)
         │
         ▼
      [verify] ──────────► (Opcional: Si existe VerifierEngine)
         │
         ├─── [¿Fallo y Reversible?] ───► [rollback] (Compensación)
         │
         ▼
     [conclude] ─────────► (Obligatorio: Formateo final de AgentOutput)
```

---

## 5. Estructura Prevista del Repositorio

```text
jg_agente/
├── README.md
├── PROJECT_CONTEXT.md
├── ISSUES.csv
├── pyproject.toml
├── Dockerfile
├── app/
│   ├── main.py                     # Bootstrap, ciclo de vida y FastAPI
│   ├── core/                       # Núcleo agnóstico del agente
│   │   ├── state.py                # AgentState y modelos base
│   │   ├── input_output.py         # AgentInput y AgentOutput
│   │   ├── tool.py                 # Contrato AgentTool y ToolResult
│   │   ├── capabilities.py         # CapabilityRegistry y detección de conflictos
│   │   ├── plugin_base.py          # Definición abstracta de BasePlugin
│   │   ├── plugin_manager.py       # Autodiscovery de plugins
│   │   └── graph/                  # Ensamblado del grafo LangGraph
│   │       ├── builder.py          # GraphBuilder condicionado por capacidades
│   │       └── nodes/              # Nodos base (reason, execute, conclude)
│   ├── security/                   # Seguridad de ejecución
│   │   ├── guard.py                # SecurityGuard y evaluación de riesgos
│   │   ├── ssrf.py                 # Validador de IPs y dominios prohibidos
│   │   └── audit.py                # SecurityAuditLogger
│   ├── persistence/                # Almacenamiento y checkpoints
│   │   ├── database.py             # Sesión SQLAlchemy / asyncpg
│   │   └── checkpointer.py         # PostgresSaver para LangGraph
│   ├── api/                        # Endpoints internos
│   │   ├── router.py
│   │   ├── executions.py           # Trigger, get, approve, reject
│   │   └── lifecycle.py            # Capabilities, health, metrics
│   └── client/                     # Comunicación con el Control Plane
│       ├── registration.py         # Protocolo de registro vía bootstrap token
│       └── heartbeat.py            # Heartbeat periódico hacia jg_dashboard
└── tests/                          # Suite integral de pruebas
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## 6. Estado Actual del Proyecto

- **Fase actual:** Arquitectura consolidada y backlog inicial de issues preparado.
- **Implementación:** Pendiente de inicio formal mediante ejecución ordenada del backlog.
- **Proyectos de referencia congelados:** `jg-ai-gateway` y `Devops60k` se mantienen como fuentes de referencia documental y extracción de código, sin modificaciones activas.

---

## 7. Roadmap de Alto Nivel

- [ ] **Fase 0:** Documentación, tooling, CI/CD y setup inicial.
- [ ] **Fase 1:** Contratos base (`AgentInput`, `AgentOutput`, `AgentTool`, `ToolResult`).
- [ ] **Fase 2:** Persistencia Core (`core_*`), checkpointer LangGraph y `SecurityGuard`.
- [ ] **Fase 3:** `CapabilityRegistry` con resolución estricta de conflictos y `PluginManager`.
- [ ] **Fase 4:** Motor de grafo dinámico y nodos base (`reason`, `execute`, `conclude`).
- [ ] **Fase 5:** Nodos avanzados de ciclo (`observe`, `plan`, `risk_assess`, `human_approval`, `verify`, `rollback`).
- [ ] **Fase 6:** API interna HTTP para ejecución y gestión de HITL.
- [ ] **Fase 7:** Cliente de registro seguro (bootstrap token 24h) y heartbeats con `jg_dashboard`.
- [ ] **Fase 8:** Implementación de `jg_plugin_conversational` (WeatherTool, NewsTool).
- [ ] **Fase 9:** **Validación Caso de Éxito A (Conversacional end-to-end)**.
- [ ] **Fase 10:** Implementación de `jg_plugin_devops` (InfraDiscovery, DAGPlanner, DockerTools, Verification).
- [ ] **Fase 11:** **Validación Caso de Éxito B (DevOps end-to-end con HITL y Rollback)**.
