# 01. Arquitectura del Runtime Cognitivo (`jg_agente`)

[← Volver al README](../README.md) | [02. Grafo Cognitivo →](02_cognitive_graph.md) | [07. Modos de Funcionamiento](07_operational_modes.md)

---

## 1. Visión de Sistema

`jg_agente` es el plano de ejecución autónomo (**Execution Plane**) del ecosistema jG. Está concebido como un microservicio privado, asíncrono y desacoplado, diseñado para operar en redes aisladas (air-gapped, VPC privadas o topologías Zero-Trust) sin exposición pública a Internet.

El motor procesa estímulos normalizados a través del contrato `AgentInput` y sintetiza respuestas estructuradas auditadas en `AgentOutput`.

```text
┌────────────────────────────────────────────────────────────────────────┐
│              INVOCADORES EXTERNOS / CONTROL PLANE / GATEWAYS           │
│        Bots Telegram · Webhooks WhatsApp · API Gateways · Dashboards   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Firmas HMAC-SHA256 (Red Privada)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      EXECUTION PLANE (jg_agente)                       │
│                                                                        │
│  ┌─────────────────────────┐            ┌───────────────────────────┐  │
│  │   FastAPI Private Core  │            │    CapabilityRegistry     │  │
│  │  /trigger  /health  HITL│            │ (Tools, Engines, Schemas) │  │
│  └────────────┬────────────┘            └─────────────▲─────────────┘  │
│               │ Invocación                            │ Registra      │
│               ▼                                       │ Capacidades   │
│  ┌─────────────────────────┐            ┌─────────────┴─────────────┐  │
│  │    LangGraph Engine     │            │      Plugins Ecosistema   │  │
│  │  (observe -> plan ->    │            │   (Empaquetados via SDK)  │  │
│  │   execute -> evaluate)  │            └───────────────────────────┘  │
│  └────────────┬────────────┘                                           │
│               │                                                        │
│               ▼                                                        │
│  ┌─────────────────────────┐            ┌───────────────────────────┐  │
│  │      SecurityGuard      │◄──────────►│    DualPostgresSaver      │  │
│  │ (SSRF, RBAC, Timeouts)  │            │   (PostgreSQL Core Views) │  │
│  └─────────────────────────┘            └───────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

## 2. Componentes Fundamentales

1. **FastAPI Private Core (`app/main.py`, `app/api/`):**
   - Expone endpoints REST en red privada (`/executions/trigger`, `/executions/{thread_id}`, `/executions/{thread_id}/approve`, `/executions/{thread_id}/reject`, `/health`, `/metrics`, `/capabilities`).
   - Valida la identidad y firma criptográfica de cada solicitud entrante mediante `verify_control_plane_auth`. Este mecanismo es completamente agnóstico al cliente y valida que la petición venga firmada con el secreto compartido del agente (`PERMANENT_AGENT_SECRET`).

2. **CapabilityRegistry (`app/core/registry.py`):**
   - Catálogo en memoria que almacena herramientas (`AgentTool`), motores (`ObserverEngine`, `PlannerEngine`, `VerifierEngine`) y modelos registrados por plugins.
   - Aplica detección de colisiones de nombres (`BootConflictError`) durante el arranque.

3. **LangGraph StateGraph (`app/core/graph.py`):**
   - Orquestador del ciclo de razonamiento y ejecución.
   - Compila dinámicamente la topología según las capacidades reales descubiertas en tiempo de ejecución.

4. **SecurityGuard (`app/security/guard.py`):**
   - Validador preventivo de seguridad que intercepta cada invocación a herramientas.
   - Ejecuta análisis contra Directory Traversal, inyecciones de comandos shell y validaciones SSRF.
   - Exige autorización humana (HITL) determinista para operaciones de riesgo `HIGH` o `CRITICAL`.

5. **DualPostgresSaver (`app/core/checkpointer.py`):**
   - Adaptador transaccional sobre PostgreSQL compatible con el ciclo asíncrono `ainvoke` de LangGraph.
   - Almacena snapshots serializados de `AgentState` sobre vistas canónicas `core_checkpoints*`.

6. **PluginManager (`app/core/plugin_manager.py`):**
   - Responsable de escanear y cargar plugins tanto locales (`plugins/`) como distribuidos vía Python `entry_points`.

---

## 3. Ciclo de Vida de Arranque, Identidad y Registro

### ¿Es el registro en un Dashboard obligatorio o bloqueante?
**Rotundamente NO por defecto (`REQUIRE_DASHBOARD_REGISTRATION=False`).**

`jg_agente` puede funcionar como un servicio totalmente autónomo. Durante el arranque (`lifespan` en `app/main.py`), la rutina `auto_register_agent` ([registration.py](../app/core/registration.py)) evalúa la configuración en el siguiente orden:

1. **Aprovisionamiento Estático (Recomendado para producción independiente):**
   - Si se definen `AGENT_ID` y `PERMANENT_AGENT_SECRET` en variables de entorno, el agente queda listo inmediatamente.
   - Si `VERIFY_CREDENTIALS_ON_BOOT=True` (activo por defecto), el agente efectúa una llamada de comprobación a `DASHBOARD_URL/api/v1/agents/heartbeat`. Si el servidor remoto no responde o la red no lo alcanza (`DashboardConnectionError`), **el agente no aborta**: registra una advertencia en el log y prosigue con el arranque en modo autónomo.
2. **Credenciales Persistidas en Disco:**
   - Si existe `.agent_credentials.json`, se cargan sus credenciales protegidas bajo permisos POSIX `0600`. Si falla la verificación de red con el dashboard, continúa operativo.
3. **Aprovisionamiento Dinámico con Bootstrap Token (`AGENT_BOOTSTRAP_TOKEN`):**
   - Diseñado para flotas elásticas. El agente contacta con `POST /api/v1/agents/register` del Dashboard para obtener su secreto permanente y guardarlo en disco. Si la conexión falla, solo bloquea el arranque si se activó explícitamente `REQUIRE_DASHBOARD_REGISTRATION=True`.
4. **Modo Desconectado / Local:**
   - Si no se suministra ninguna credencial, arranca como `jg_agente_local` en modo desarrollo.

---

## 4. Validación Fail-Fast de Integridad en Boot (`app/core/boot.py`)

Para garantizar que ningún contenedor o instancia del agente acepte tráfico productivo si su perfil operativo se encuentra incompleto o degradado, `app/main.py` ejecuta la verificación estricta `validate_boot_capabilities` ([app/core/boot.py](../app/core/boot.py)):

1. **Requerimientos de Perfil por Configuración:**
   - **`REQUIRED_PLUGINS`:** Lista obligatoria de nombres de plugins que deben haberse descubierto e inicializado.
   - **`REQUIRED_TOOLS`:** Lista de nombres específicos de herramientas (`AgentTool`) que deben existir en el catálogo.
   - **`REQUIRE_PLANNER`:** Exige la presencia obligatoria de un motor `PlannerEngine` registrado.
   - **`REQUIRE_OBSERVER`:** Exige la presencia obligatoria de un motor `ObserverEngine` registrado.
   - **`REQUIRE_VERIFIER`:** Exige la presencia obligatoria de un motor `VerifierEngine` registrado.

2. **Validación Estructural de Herramientas:**
   - Cada herramienta registrada se inspecciona deterministamente: debe tener una función ejecutable `callable(tool.func)` y una categoría no vacía asignada.

3. **Excepción Crítica `BootIntegrityError`:**
   - Si alguna capacidad exigida falta o una herramienta no supera la inspección de integridad, el sistema registra el fallo a nivel `CRITICAL` y lanza `BootIntegrityError`, abortando el arranque de inmediato (*Fail-Fast*) para que los orquestadores (Docker Compose, Kubernetes) detecten el estado no preparado del contenedor.

---

## 5. Trazabilidad Distribuida y Contexto de Logs (`app/core/correlation.py`)

La trazabilidad transversal entre clientes externos, `jg_dashboard` y `jg_agente` se gestiona a través del módulo [app/core/correlation.py](../app/core/correlation.py):

1. **`CorrelationIdMiddleware` (ASGI):**
   - Intercepta cada solicitud HTTP entrante buscando la cabecera `X-Correlation-ID`.
   - Si no viene informada, genera automáticamente un identificador único `UUIDv4`.
   - Inyecta la cabecera `X-Correlation-ID` en la respuesta HTTP saliente y la asigna a `request.state.correlation_id`.

2. **Aislamiento Asíncrono con `ContextVar`:**
   - El identificador se propaga mediante `contextvars.ContextVar("correlation_id")`, garantizando que cada tarea concurrente en el `asyncio` event loop mantenga su propio ID sin contaminación cruzada.

3. **Inyección Automática en Logs (`CorrelationLogFilter`):**
   - Se instala un filtro de logging global que antepone automáticamente la etiqueta `[<correlation_id>] ` en cada mensaje de registro emitido durante el procesamiento del hilo, facilitando el filtrado en sistemas centralizados de agregación de logs (Grafana Loki, Kibana, CloudWatch).

---

## 6. Navegación

- [← Volver al README Principal](../README.md)
- [Siguiente: 02. Grafo Cognitivo y Máquina de Estados →](02_cognitive_graph.md)
- [Ver también: 07. Modos de Funcionamiento, Topologías y Registro](07_operational_modes.md)

