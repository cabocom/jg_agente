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

## 5. Estructura del Repositorio

```text
jg_agente/
├── .gitlab-ci.yml                  # Pipeline CI/CD a registry.cabocom.net
├── Dockerfile                      # Multi-stage build optimizado
├── docker-compose.yml              # Orquestación local con PostgreSQL
├── .env.example                    # Plantilla de variables de entorno
├── pyproject.toml                  # Dependencias y configuración de herramientas
├── alembic.ini                     # Configuración de migraciones
├── alembic/
│   ├── env.py                      # Entorno async de Alembic con filtro core_
│   └── versions/
│       └── 0001_initial_core_tables.py # Migración de core_executions y core_audit_records
├── app/
│   ├── __init__.py                 # Versión del paquete
│   ├── main.py                     # Bootstrap FastAPI y ciclo de vida
│   ├── core/
│   │   ├── boot.py                 # Validación en boot, comprobación de integridad y arranque
│   │   ├── checkpointer.py         # PostgresSaver, MemorySaver y vistas core_checkpoints
│   │   ├── config.py               # Configuración centralizada Pydantic
│   │   ├── graph.py                # GraphBuilder agnóstico de LangGraph y topologías dinámicas
│   │   ├── llm.py                  # MockChatModel, OpenAICompatibleChatModel y factoría get_chat_model
│   │   ├── plugin_manager.py       # PluginManager: autodescubrimiento y resolución de dependencias
│   │   └── registry.py             # CapabilityRegistry y detección estricta de conflictos (BootConflictError)
│   ├── db/
│   │   ├── base.py                 # DeclarativeBase y convención estricta core_
│   │   ├── models.py               # Modelos ORM: CoreExecution y CoreAuditRecord
│   │   └── session.py              # async_engine y factoría de sesiones asyncpg
│   ├── models/
│   │   ├── io.py                   # Contratos AgentInput y AgentOutput
│   │   ├── state.py                # AgentState, PolicyDecision, SecurityEvaluationResult
│   │   └── tools.py                # Contratos AgentTool y ToolResult
│   ├── nodes/
│   │   ├── __init__.py             # Exportación de nodos base del grafo
│   │   ├── conclude.py             # Nodo base conclude: unificación de salida, formateo AgentOutput y métricas
│   │   ├── execute.py              # Nodo base execute: ejecución secuencial, sandbox SecurityGuard y rollback_context
│   │   ├── observe.py              # Nodo opcional observe: telemetría agnóstica de entorno con ObserverEngine
│   │   └── reason.py               # Nodo base reason: inferencia LLM, tool binding y decisión de flujo
│   ├── plugins/
│   │   ├── __init__.py             # Exportación BasePlugin, BaseEngine, PluginMetadata
│   │   └── base.py                 # Interfaz abstracta BasePlugin, ciclo de vida y BaseEngine
│   └── security/
│       ├── audit.py                # SecurityAuditLogger (persistencia no bloqueante)
│       ├── guard.py                # SecurityGuard (interceptor de ejecución, permisos y HITL)
│       └── ssrf.py                 # SSRFValidator (bloqueo RFC 1918, metadata y loopback)
├── docs/                           # Documentación técnica viva
│   ├── architecture.md             # Visión del Execution Plane y ciclo cognitivo
│   ├── models.md                   # Contratos canónicos I/O, Tools y Estado
│   ├── database.md                 # Persistencia relacional, convención core_ y Alembic
│   ├── checkpointer.md             # Checkpointer LangGraph sobre PostgreSQL
│   ├── security.md                 # SecurityGuard, auditoría inmutable y protección SSRF
│   ├── plugins.md                  # Sistema de plugins, BasePlugin y ciclo de vida
│   ├── graph.md                    # Ensamblador GraphBuilder, contratos de nodos y StateSnapshot
│   └── issues/                     # Trazabilidad técnica por issue
├── tests/                          # Suite integral de pruebas (Unit + Integration)
│   ├── test_bootstrap.py
│   ├── test_health_endpoint.py
│   ├── test_io_models.py
│   ├── test_tool_models.py
│   ├── test_agent_state.py
│   ├── test_database_migrations.py
│   ├── test_checkpointer.py
│   ├── test_security_audit.py
│   ├── test_ssrf_validator.py
│   ├── test_security_guard.py
│   ├── test_base_plugin.py
│   ├── test_capability_registry.py
│   ├── test_plugin_manager.py
│   ├── test_boot_validation.py
│   ├── test_graph_builder.py
│   ├── test_node_reason.py
│   ├── test_node_execute.py
│   ├── test_node_conclude.py
│   └── test_node_observe.py
└── scripts/
    └── check.sh                    # Verificación integral (Ruff + MyPy + Pytest)
```

---

## 6. Documentación Técnica

La documentación exhaustiva del proyecto se encuentra disponible en [`docs/`](docs/):
- **[Arquitectura General](docs/architecture.md):** Separación de planos, ciclo de ejecución y principios.
- **[Contratos y Modelos Core](docs/models.md):** `AgentInput`, `AgentOutput`, `AgentTool` y `AgentState`.
- **[Base de Datos y Alembic](docs/database.md):** Convención `core_`, esquemas y migraciones asíncronas.
- **[Checkpointer LangGraph](docs/checkpointer.md):** Persistencia sobre PostgreSQL (`core_checkpoints`) y pausado HITL.
- **[Seguridad y Auditoría](docs/security.md):** `SecurityGuard`, `SecurityAuditLogger`, trazabilidad inmutable y protección contra SSRF.
- **[Plugins y Extensibilidad](docs/plugins.md):** `BasePlugin`, `BaseEngine`, `CapabilityRegistry` y `PluginManager`.
- **[Grafo y Flujos Cognitivos](docs/graph.md):** `GraphBuilder` agnóstico, nodos canónicos y `StateSnapshot`.

---

## 7. Verificación de Calidad

Para ejecutar el formateador, linter, análisis de tipos estricto y la suite de tests:

```bash
./scripts/check.sh
```

---

## 8. Estado del Proyecto y Roadmap

- [x] **Fase 01:** Setup inicial, Dockerfile, docker-compose, scripts de verificación y CI/CD con GitLab.
- [x] **Fase 02:** Contratos Core (`AgentInput`, `AgentOutput`, `AgentTool`, `ToolResult`, compensación de rollback, `AgentState`).
- [x] **Fase 03:** Persistencia, Checkpointing y Seguridad Base:
  - [x] `ISSUE-F03-T01`: Motor PostgreSQL async, convención `core_*` y migraciones Alembic.
  - [x] `ISSUE-F03-T02`: Checkpointer LangGraph (`PostgresSaver`) sobre vistas `core_checkpoints`.
  - [x] `ISSUE-F03-T03`: `SecurityAuditLogger` inmutable no bloqueante sobre `core_audit_records`.
  - [x] `ISSUE-F03-T04`: Validador de protección SSRF para herramientas de red (`SSRFValidator`).
  - [x] `ISSUE-F03-T05`: Interceptor central de seguridad `SecurityGuard` (permisos, inyecciones, SSRF, HITL y auditoría).
- [x] **Fase 04:** CapabilityRegistry y Sistema de Plugins Core (100%):
  - [x] `ISSUE-F04-T01`: Definición de interfaz abstracta `BasePlugin` y ciclo de vida.
  - [x] `ISSUE-F04-T02`: Implementación de `CapabilityRegistry` con detección estricta de conflictos.
  - [x] `ISSUE-F04-T03`: Implementación de `PluginManager` con autodiscovery.
  - [x] `ISSUE-F04-T04`: Validación en boot del agente contra `CapabilityRegistry`.
- [x] **Fase 05:** Ensamblado del Grafo LangGraph y Nodos Base (100%):
  - [x] `ISSUE-F05-T01`: Implementación del `GraphBuilder` agnóstico de LangGraph (sin bifurcaciones de dominio y con `StateSnapshot` funcional).
  - [x] `ISSUE-F05-T02`: Implementación de nodo base: `reason` (inferencia LLM, tool binding dinámico y memoria conversacional).
  - [x] `ISSUE-F05-T03`: Implementación de nodo base: `execute` (ejecución secuencial sandboxed, SecurityGuard y rollback_context).
  - [x] `ISSUE-F05-T04`: Implementación de nodo base: `conclude` (unificación de salida, AgentOutput y métricas de tiempo).
- [ ] **Fase 06:** Nodos Opcionales y Motores Cognitivos:
  - [x] `ISSUE-F06-T01`: Implementación de nodo opcional: `observe` (telemetría de entorno desacoplada y ObserverEngine).
- [ ] **Fase 07:** Exposición API REST (`POST /executions/trigger`, HITL) y Bootstrap del Agente.
- [ ] **Fase 08:** Integración con plugins de dominio y validación end-to-end.
